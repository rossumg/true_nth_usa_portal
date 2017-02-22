"""SitePersistence Module"""
from collections import defaultdict
from flask import current_app
import json
import os
import requests
from sqlalchemy import exc, and_
from StringIO import StringIO
import tempfile

from app import SITE_CFG
from extensions import db
from models.app_text import AppText
from models.fhir import FHIR_datetime
from models.intervention import Intervention, INTERVENTION
from models.intervention_strategies import AccessStrategy
from models.organization import Organization

def dict_compare(d1, d2):
    """Deep order independent comparison of two dictionaries

    returns lists of: added, removed, modified, same
    """
    d1_keys = set(d1.keys())
    d2_keys = set(d2.keys())
    intersect_keys = d1_keys.intersection(d2_keys)
    added = d1_keys - d2_keys
    removed = d2_keys - d1_keys
    modified = {o : (d1[o], d2[o]) for o in intersect_keys if d1[o] != d2[o]}
    same = set(o for o in intersect_keys if d1[o] == d2[o])
    return added, removed, modified, same

def dict_match(newd, oldd, diff_stream):
    """Returns true/false, if the two dicts contain same key/values

    Compares deep structure, ignores key order

    :param newd: First dict to compare, i.e. new state
    :param oldd: Second dict, i.e. current or old state
    :param diff_stream: StringIO like object to report dif details
    :return: True if the two dictionaries match, False with details in
        diff_stream otherwise

    """
    added, removed, modified, same = dict_compare(newd, oldd)
    if len(same) == len(newd.keys()) and len(newd.keys()) == len(oldd.keys()):
        assert not added
        assert not removed
        assert not modified
        return True
    else:
        if added:
            diff_stream.write(
                "added {}\n".format({k:newd.get(k) for k in added}))
        if removed:
            diff_stream.write(
                "removed {}\n".format({k:oldd.get(k) for k in removed}))
        if modified:
            for k in modified.keys():
                diff_stream.write(
                    "replace {} with {}\n".format(
                        {k:oldd.get(k)},{k:newd.get(k)}))
        return False

class SitePersistence(object):
    """Manage import and export of dynamic site data"""

    VERSION = '0.1'

    def persistence_filename(self, read_only=True):
        """Returns the configured persistence file

        :param read_only: for imports (default), only read is needed.
                          Set False for exports, which require write.

        Using the first value found, looks for a variable named
        `PERSISTENCE_FILE` in the configuration file(s) and then as an
        environment variable.

        For imports (read_only), the value of `PERSISTENCE_FILE` may point
        to a repository file such as
        `https://raw.githubusercontent.com/uwcirg/TrueNTH-USA-site-config/master/site_persistence_file.json`

        Exports naturally require write permission, and must therefore point
        to a writeable filesystem path.

        """
        env_file = os.environ.get('PERSISTENCE_FILE')
        config_file = current_app.config.get("PERSISTENCE_FILE", '')

        filename = config_file if config_file else env_file
        if not filename:
            raise ValueError('PERSISTENCE_FILE not defined as environment '
                             'variable nor in a config file')
        if filename.startswith('http'):
            if not read_only:
                raise ValueError('PERSISTENCE_FILE value not on filesystem; '
                                 'cannot export to remote file {}'.format(
                                     filename))
            filename = self.pull_latest(filename)
        return filename

    def pull_latest(self, url):
        """Given a remote URL - pull file into temp dir and return path"""
        r = requests.get(url)
        with tempfile.NamedTemporaryFile(delete=False) as file:
            file.write(r.content)
            self.tmpfile = file.name
            self._log("wrote {} contents to tempfile {}".format(
                url, self.tmpfile))
        return self.tmpfile

    def _log(self, msg):
        current_app.logger.info(msg)

    def __write__(self, data):
        self.filename = self.persistence_filename(read_only=False)
        if data:
            with open(self.filename, 'w') as f:
                f.write(json.dumps(data, indent=2, sort_keys=True))
            self._log("Wrote site persistence to `{}`".format(self.filename))

    def __read__(self):
        self.filename = self.persistence_filename(read_only=True)
        with open(self.filename, 'r') as f:
            data = json.load(f)
        if hasattr(self, 'tmpfile'):
            os.remove(self.tmpfile)
            del self.tmpfile
        return data

    def __del__(self):
        if hasattr(self, 'tmpfile'):
            raise ValueError("tmpfile {} wasn't cleaned "
                             "up!".format(self.tmpfile))

    def __header__(self, data):
        data['resourceType'] = 'Bundle'
        data['id'] = 'SitePersistence v{}'.format(self.VERSION)
        data['meta'] = {'fhir_comments': [
            "export of dynamic site data from host",
            "{}".format(current_app.config.get('SERVER_NAME'))],
            'lastUpdated': FHIR_datetime.now()}
        data['type'] = 'document'
        return data

    def __verify_header__(self, data):
        """Make sure header conforms to what we're looking for"""
        if data.get('resourceType') != 'Bundle':
            raise ValueError("expected 'Bundle' resourceType not found")
        if data.get('id') != 'SitePersistence v{}'.format(self.VERSION):
            raise ValueError("unexpected SitePersistence version {}".format(
                self.VERSION))

    def export(self):
        """Generate single JSON file defining dynamic site objects

        Export dynamic data, such as Organizations and Access Strategies for
        import into other sites.  This does NOT export values expected
        to live in the site config file or the static set generated by the seed
        managment command.

        To import the data, use the seed command as defined in manage.py
        """
        d = self.__header__({})
        d['entry'] = []

        # Add organizations
        orgs = Organization.generate_bundle()
        d['entry'] += orgs['entry']

        # Add strategies (AKA access rules)
        # and sharable portions of interventions
        for intervention in INTERVENTION:
            d['entry'].append(intervention.as_json())
            rules = [x.as_json() for x in
                     intervention.access_strategies]
            if rules:
                d['entry'] += rules

        # Add customized app strings
        app_strings = AppText.query.all()
        for app_string in app_strings:
            d['entry'].append(app_string.as_json())

        # Add site.cfg
        config_data = read_site_cfg()
        d['entry'].append(config_data)

        self.__write__(d)

    def import_(self, include_interventions, keep_unmentioned):
        """If persistence file is found, import the data

        :param include_interventions: if True, intervention data in the
            persistence file will be included (and potentially replace
            existing intervention state).  if False, intervention data
            will be ignored.

        :param keep_unmentioned: if True, unmentioned data, such as
            an organization or intervention in the current database
            but not in the persistence file, will be left in place.
            if False, any unmentioned data will be purged as part of
            the import process.

        """
        data = self.__read__()
        self.__verify_header__(data)

        # Fragile design requires items are imported in order
        # Referenced objects must exist before import will succeed.

        objs_by_type = defaultdict(list)
        for entry in data['entry']:
            objs_by_type[entry['resourceType']].append(entry)

        def update_org(org_fhir):
            org = Organization.from_fhir(org_fhir)
            existing = Organization.query.get(org.id)
            if existing:
                details = StringIO()
                if not dict_match(org_fhir, existing.as_fhir(), details):
                    self._log("Organization {id} collision on "
                              "import.  {details}".format(
                                  id=org.id, details=details.getvalue()))
                    existing.update_from_fhir(org_fhir)
            else:
                self._log("org {} not found - importing".format(org.id))
                db.session.add(org)

        def update_strat(strat_json):
            strat = AccessStrategy.from_json(strat_json)
            existing = AccessStrategy.query.get(strat.id) if strat.id else None
            if existing:
                details = StringIO()
                if not dict_match(strat_json, existing.as_json(), details):
                    self._log("AccessStrategy {id} collision on "
                              "import.  {details}".format(
                                  id=org.id, details=details.getvalue()))
                    db.session.delete(existing)
                    db.session.add(strat)
            else:
                self._log("AccessStrategy {} not found, "
                          "importing".format(strat.id))
                db.session.add(strat)

        def update_intervention(intervention_json):
            existing = Intervention.query.filter_by(
                name=intervention_json['name']).first()
            existing_json = existing.as_json() if existing else None
            intervention = Intervention.from_json(intervention_json)
            if existing:
                details = StringIO()
                if not dict_match(intervention_json, existing_json, details):
                    if include_interventions:
                        self._log("Intervention {id} collision on "
                                  "import.  {details}".format(
                                      id=intervention.id,
                                      details=details.getvalue()))
                        db.session.delete(existing)
                        db.session.add(intervention)
                    else:
                        print ("WARNING: include_interventions not set and "
                               "'{}' differs with persistence".format(
                                   intervention.description))
                        print "{}".format(details.getvalue())
                        db.session.expunge(intervention)
            else:
                if include_interventions:
                    self._log("Intervention {} not found, "
                              "importing".format(intervention.id))
                    db.session.add(intervention)
                else:
                    print ("WARNING: include_interventions not set and "
                           "'{}' not present".format(
                               intervention_json))
                    db.session.expunge(intervention)

        # Orgs first:
        max_org_id = 0
        orgs_seen = []
        for o in objs_by_type['Organization']:
            max_org_id = max(max_org_id, o.get('id', 0))
            update_org(o)
            orgs_seen.append(o['id'])
            # As orgs can refer to other orgs, must commit on the
            # fly to avoid lookup errors
            db.session.commit()

        # Delete any orgs not named
        if not keep_unmentioned:
            # partOf self reference demands these are taken down in order
            # first the children naming a partOf reference
            for org in Organization.query.filter(and_(
                ~Organization.id.in_(orgs_seen),
                Organization.partOf_id != None)):
                current_app.logger.info(
                    "Deleting organization not mentioned in "
                    "site_persistence: {}".format(org))
                db.session.delete(org)
            # then the parents
            for org in Organization.query.filter(and_(
                ~Organization.id.in_(orgs_seen),
                Organization.partOf_id == None)):
                current_app.logger.info(
                    "Deleting organization not mentioned in "
                    "site_persistence: {}".format(org))
                db.session.delete(org)

        # Intervention details
        interventions_seen = []
        for i in objs_by_type['Intervention']:
            update_intervention(i)
            interventions_seen.append(i['name'])

        db.session.commit()  # strategies may use interventions, must exist

        # Delete any interventions not named
        if not keep_unmentioned:
            for intervention in Intervention.query.filter(
                ~Intervention.name.in_(interventions_seen)):
                if include_interventions:
                    current_app.logger.info(
                        "Deleting Intervention not mentioned in "
                        "site_persistence: {}".format(intervention))
                    db.session.delete(intervention)
                else:
                    print ("WARNING: include_interventions not set and "
                           "'{}' in db but not in persistence".format(
                               intervention))

        # Access rules next
        max_strat_id = 0
        strategies_seen = []
        for s in objs_by_type['AccessStrategy']:
            max_strat_id = max(max_strat_id, s.get('id', 0))
            update_strat(s)
            strategies_seen.append(s['id'])

        # Delete any strategies not named
        if not keep_unmentioned:
            for strategy in AccessStrategy.query.filter(
                ~AccessStrategy.id.in_(strategies_seen)):
                current_app.logger.info(
                    "Deleting AccessStrategy not mentioned in "
                    "site_persistence: {}".format(strategy))
                db.session.delete(strategy)

        # App Text shouldn't be order dependent, now is good.
        apptext_seen = []
        for a in objs_by_type['AppText']:
            AppText.from_json(a)
            apptext_seen.append(a['name'])

        # Delete any AppTexts not named
        if not keep_unmentioned:
            for apptext in AppText.query.filter(
                ~AppText.name.in_(apptext_seen)):
                current_app.logger.info(
                    "Deleting AppText not mentioned in "
                    "site_persistence: {}".format(repr(apptext)))
                db.session.delete(apptext)

        # Config isn't order dependent, now is good.
        assert len(objs_by_type[SITE_CFG]) < 2
        for c in objs_by_type[SITE_CFG]:
            write_site_cfg(c)

        db.session.commit()

        # Bump sequence numbers if necessary to avoid unique constraint
        # violations in the future, as we may have manually inserted ids
        # without using the sequence from the persistence file.
        def fix_sequence(seq_id, max_known):
            try:
                currval = db.engine.execute(
                    "select currval('{}')".format(seq_id))
            except exc.OperationalError as oe:
                if 'not yet defined' in str(oe):
                    currval = db.engine.execute(
                        "select nextval('{}')".format(seq_id))
            if currval.fetchone()[0] < max_known:
                db.engine.execute(
                    "SELECT setval('{}', {})".format(seq_id, max_org_id))

        fix_sequence('organizations_id_seq', max_org_id)
        fix_sequence('access_strategies_id_seq', max_strat_id)
        self._log("SitePersistence import complete")


def read_site_cfg():
    cfg_file = os.path.join(current_app.instance_path, SITE_CFG)
    with open(cfg_file, 'r') as fp:
        results = [line for line in fp.readlines()]
    # Package for inclusion
    d = {"resourceType": SITE_CFG,
         "results": results}
    return d

def write_site_cfg(data):
    cfg_file = os.path.join(current_app.instance_path, SITE_CFG)
    assert data.get('resourceType') == SITE_CFG
    with open(cfg_file, 'w') as fp:
        for line in data['results']:
            fp.write(line)
