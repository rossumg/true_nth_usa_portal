"""User model """
from datetime import datetime
from dateutil import parser
from flask import abort, request, session
from flask.ext.user import UserMixin, _call_or_get
from sqlalchemy import and_, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM
from flask.ext.login import current_user as flask_login_current_user

from ..audit import auditable_event
from ..extensions import db
from .fhir import as_fhir, Observation, UserObservation
from .fhir import CodeableConcept, ValueQuantity
from .relationship import Relationship, RELATIONSHIP
from .role import Role, ROLE

# http://hl7.org/fhir/v3/AdministrativeGender/
gender_types = ENUM('male', 'female', 'undifferentiated', name='genders',
                    create_type=False)


class User(db.Model, UserMixin):
    __tablename__ = 'users'  # Override default 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), default="Anonymous")
    first_name = db.Column(db.String(64))
    last_name = db.Column(db.String(64))
    registered = db.Column(db.DateTime, default=datetime.now)
    email = db.Column(db.String(120), unique=True)
    phone = db.Column(db.String(40), unique=True)
    gender = db.Column('gender', gender_types)
    birthdate = db.Column(db.Date)
    image_url = db.Column(db.Text)
    active = db.Column('is_active', db.Boolean(), nullable=False,
            server_default='1')
    locale_id = db.Column(db.ForeignKey('codeable_concepts.id'))
    timezone = db.Column(db.String(20), default='UTC')

    # Only used for local accounts
    password = db.Column(db.String(255))
    reset_password_token = db.Column(db.String(100))
    confirmed_at = db.Column(db.DateTime())

    observations = db.relationship('Observation', lazy='dynamic',
            secondary="user_observations", backref=db.backref('users'))
    roles = db.relationship('Role', secondary='user_roles',
            backref=db.backref('users', lazy='dynamic'))
    locale = db.relationship(CodeableConcept, cascade="save-update")

    def add_observation(self, fhir):
        if not 'coding' in fhir['code']:
            return 400, "requires at least one CodeableConcept"
        if not 'valueQuantity' in fhir:
            return 400, "missing required 'valueQuantity'"

        # Only retaining first Codeable Concept at this time
        if len(fhir['code']['coding']) > 1:
            return 400, "can't handle multiple codeable concepts"
        first_cc = fhir['code']['coding'][0]
        cc = CodeableConcept(system=first_cc.get('system'),
                code=first_cc.get('code'),
                display=first_cc.get('display')).add_if_not_found()

        v = fhir['valueQuantity']
        vq = ValueQuantity(value=v.get('value'),
                units=v.get('units'),
                system=v.get('system'),
                code=v.get('code')).add_if_not_found()

        issued = fhir.get('issued') and\
                parser.parse(fhir.get('issued')) or None
        observation = Observation(status=fhir.get('status'),
                issued=issued,
                codeable_concept_id=cc.id,
                value_quantity_id=vq.id).add_if_not_found()

        UserObservation(user_id=self.id,
                observation_id=observation.id).add_if_not_found()
        return 200, "ok"

    def add_relationship(self, other_user, relationship_name):
        # confirm it's not already defined
        relationship = Relationship.query.filter_by(
                name=relationship_name).first()
        existing = UserRelationship.query.filter_by(user_id=self.id,
                other_user_id=other_user.id,
                relationship_id=relationship.id).first()
        if existing:
            raise ValueError("requested relationship already defined")

        new_relationship = UserRelationship(user_id=self.id,
                other_user_id=other_user.id,
                relationship_id=relationship.id)
        self.relationships.append(new_relationship)

    def has_relationship(self, relationship_name, other_user):
        relationship = Relationship.query.filter_by(
                name=relationship_name).first()
        for r in self.relationships:
            if (r.relationship_id == relationship.id and
                r.other_user_id == other_user.id):
                return True
        return False

    def add_service_account(self):
        """Service account generation.

        For automated, authenticated access to protected API endpoints,
        a service user can be created and used to generate a long-life
        bearer token.  The account is a user with the service role,
        attached to a sposor account - the (self) individual creating it.

        Only a single service account is allowed per user.  If one is
        found to exist for this user, simply return it.

        """
        for rel in self.relationships:
            if rel.relationship.name == RELATIONSHIP.SPONSOR:
                return User.query.get(rel.other_user_id)

        service_user = User(username=(u'service account sponsored by {}'.
                              format(self.username)))
        db.session.add(service_user)
        add_role(service_user, ROLE.SERVICE)
        self.add_relationship(service_user, RELATIONSHIP.SPONSOR)
        auditable_event("Service account created by", user_id=self.id)
        return service_user

    def fetch_values_for_concept(self, codeable_concept):
        """Return any matching ValueQuantities for this user"""
        # User may not have persisted concept - do so now for match
        codeable_concept = codeable_concept.add_if_not_found()

        return [obs.value_quantity for obs in self.observations if\
                obs.codeable_concept_id == codeable_concept.id]

    def save_constrained_observation(self, codeable_concept, value_quantity):
        """Add or update the value for given concept as observation

        We can store any number of observations for a patient, and
        for a given concept, any number of values.  BUT sometimes we
        just want to update the value and retain a single observation
        for the concept.  Use this method is such a case, i.e. for
        a user's 'biopsy' status.

        """
        # User may not have persisted concept or value - CYA
        codeable_concept = codeable_concept.add_if_not_found()
        value_quantity = value_quantity.add_if_not_found()

        existing = [obs for obs in self.observations if\
                    obs.codeable_concept_id == codeable_concept.id]
        assert len(existing) < 2  # it's a constrained concept afterall

        if existing:
            if existing[0].value_quantity_id == value_quantity.id:
                # perfect match -- done
                return
            else:
                # We don't want multiple observations for this concept
                # with different values.  Delete old and add new
                self.observations.remove(existing[0])

        observation = Observation(codeable_concept_id=codeable_concept.id,
                                  value_quantity_id=value_quantity.id)
        self.observations.append(observation.add_if_not_found())

    def clinical_history(self, requestURL=None):
        now = datetime.now()
        fhir = {"resourceType": "Bundle",
                "title": "Clinical History",
                "link": [{"rel": "self", "href": requestURL},],
                "updated": as_fhir(now),
                "entry": []}

        for ob in self.observations:
            fhir['entry'].append({"title": "Patient Observation",
                    "updated": as_fhir(now),
                    "author": [{"name": "Truenth Portal"},],
                    "content": ob.as_fhir()})
        return fhir

    def as_fhir(self):
        d = {}
        d['resourceType'] = "Patient"
        d['identifier'] = []
        d['identifier'].append({'label': 'Truenth identifier',
                    'value': self.id})
        d['identifier'].append({'label': 'Truenth username',
                    'value': self.username})
        d['name'] = {}
        if self.first_name:
            d['name']['given'] = self.first_name
        if self.last_name:
            d['name']['family'] = self.last_name
        if self.birthdate:
            d['birthDate'] = as_fhir(self.birthdate)
        if self.gender:
            d['gender'] = {'coding': [{'system':
                "http://hl7.org/fhir/v3/AdministrativeGender",
                'code': self.gender[0].upper(),
                'display': self.gender.capitalize()}]}
        d['status'] = 'registered' if self.registered else 'unknown'
        if self.locale:
            d['communication'] = [{"language": self.locale.as_fhir()}]
        d['telecom'] = []
        d['photo'] = []
        if self.email:
            d['telecom'].append({'system': 'email', 'value': self.email})
        if self.phone:
            d['telecom'].append({'system': 'phone', 'value': self.phone})
        if self.image_url:
            d['photo'].append({'url': self.image_url})
        return d

    def update_username(self, force=False):
        """Update username from self.first_name, self.last_name

        @param force: Default behavior only updates if username is
        currently 'Anonymous'.  Set force=True to override.

        """
        if not force and self.username != 'Anonymous':
            return
        # Find a unique username
        similar = User.query.filter(and_(User.username.like('{0} {1}%'.format(
            self.first_name, self.last_name)), User.id != self.id))
        if not similar.count():
            self.username = '{0} {1}'.format(self.first_name, self.last_name)
        else:
            n = similar.count()
            while True:
                # start with the len and keep incrementing till we don't match
                attempt = '{0} {1} {2}'.format(
                    self.first_name, self.last_name, n)
                if attempt not in [sim.username for sim in similar]:
                    self.username = attempt
                    break
                else:
                    n += 1

    def update_from_fhir(self, fhir):
        def v_or_n(value):
            """Return None unless the value contains data"""
            return value.rstrip() or None

        if 'name' in fhir:
            self.first_name = v_or_n(fhir['name']['given']) or self.first_name
            self.last_name = v_or_n(fhir['name']['family']) or self.last_name
            self.update_username()
        if 'birthDate' in fhir:
            self.birthdate = datetime.strptime(fhir['birthDate'],
                    '%Y-%m-%d')
        if 'gender' in fhir:
            self.gender = fhir['gender']['coding'][0]['display'].lower()
        if 'telecom' in fhir:
            for e in fhir['telecom']:
                if e['system'] == 'email':
                    self.email = v_or_n(e['value'])
                if e['system'] == 'phone':
                    self.phone = v_or_n(e['value'])
        if 'communication' in fhir:
            for e in fhir['communication']:
                if 'language' in e:
                    self.locale = CodeableConcept.from_fhir(e['language'])
        db.session.add(self)

    def check_role(self, permission, other_id):
        """check user for adequate role

        if user is an admin or a service account, grant carte blanche
        otherwise, must be self or have a relationship granting permission
        to "verb" the other user.

        returns true if permission should be granted, otherwise raise a 401

        """
        if self.id == other_id:
            return True
        for role in self.roles:
            if role.name in (ROLE.ADMIN, ROLE.SERVICE):
                return True
        # TODO: address permission details, etc.
        abort(401, "Inadequate role for %s of %d" % (permission, other_id))

    def has_role(self, role_name):
        return role_name in [r.name for r in self.roles]


def add_authomatic_user(authomatic_user, image_url):
    """Given the result from an external IdP, create a new user"""
    user = User(username=authomatic_user.name,
            first_name=authomatic_user.first_name,
            last_name=authomatic_user.last_name,
            birthdate=authomatic_user.birth_date,
            gender=authomatic_user.gender,
            email=authomatic_user.email,
            image_url=image_url)
    db.session.add(user)
    return user


def add_anon_user():
    """Anonymous user generation.

    Acts like real user without any authentication.  Used to persist
    data and handle similar communication with client apps (interventions).

    Bound to the session - an anonymous user can also be promoted to
    a real user at a later time in the session.

    """
    user = User(username='Anonymous')
    db.session.add(user)
    add_role(user, ROLE.ANON)
    return user


class RoleError(ValueError):
    pass


def add_role(user, role_name):
    role = Role.query.filter_by(name=role_name).first()
    assert(role)
    # don't allow promotion of service users
    if user.has_role(ROLE.SERVICE):
        raise RoleError("service accounts can't be promoted")

    new_role = UserRoles(user_id=user.id,
            role_id=role.id)
    db.session.add(new_role)
    return user


def current_user():
    """Obtain the "current" user object

    Works for both remote oauth sessions and locally logged in sessions.

    returns current user object, or None if not logged in (local or remote)
    """
    uid = None
    if 'id' in session:
        # Locally logged in
        uid = session['id']
    elif _call_or_get(flask_login_current_user.is_authenticated):
        uid = flask_login_current_user.id
    elif hasattr(request, 'oauth'):
        # Remote OAuth - 'id' lives in request.oauth.user.id:
        uid = request.oauth.user.id
    if uid:
        with db.session.no_autoflush:
            return User.query.get(uid)
    return None


def get_user(uid):
    return User.query.get(uid)


class UserRoles(db.Model):
    id = db.Column(db.Integer(), primary_key=True)
    user_id = db.Column(db.Integer(), db.ForeignKey('users.id',
        ondelete='CASCADE'))
    role_id = db.Column(db.Integer(), db.ForeignKey('roles.id',
        ondelete='CASCADE'))

    __table_args__ = (UniqueConstraint('user_id', 'role_id',
        name='_user_role'),)


class UserRelationship(db.Model):
    """SQLAlchemy class for `user_relationships` table

    Relationship is assumed to be ordered such that:
        <user_id> has a <relationship.name> with <other_user_id>

    """
    __tablename__ = 'user_relationships'
    id = db.Column(db.Integer(), primary_key=True)
    user_id = db.Column(db.Integer(), db.ForeignKey('users.id',
        ondelete='CASCADE'))
    other_user_id = db.Column(db.Integer(), db.ForeignKey('users.id',
        ondelete='CASCADE'))
    relationship_id = db.Column(db.Integer(),
        db.ForeignKey('relationships.id', ondelete='CASCADE'))

    user = db.relationship("User", backref='relationships',
                           foreign_keys=[user_id])
    other_user = db.relationship("User",
        foreign_keys=[other_user_id])
    relationship = db.relationship("Relationship",
        foreign_keys=[relationship_id])

    __table_args__ = (UniqueConstraint('user_id', 'other_user_id',
        'relationship_id', name='_user_relationship'),)
