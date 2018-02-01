"""Unit test module for Practitioner module"""
from flask_webtest import SessionScope
import json

from portal.extensions import db
from portal.models.audit import Audit
from portal.models.identifier import Identifier
from portal.models.practitioner import Practitioner
from portal.models.role import ROLE
from tests import TestCase


class TestPractitioner(TestCase):
    """Practitioner model and view tests"""

    def test_practitioner_search(self):
        pract1 = Practitioner(first_name="Indiana", last_name="Jones")
        pract2 = Practitioner(first_name="John", last_name="Watson")
        pract3 = Practitioner(first_name="John", last_name="Zoidberg")
        ident = Identifier(system="testsys", _value="testval")
        pract1.identifiers.append(ident)
        with SessionScope(db):
            db.session.add(pract1)
            db.session.add(pract2)
            db.session.add(pract3)
            db.session.commit()

        self.login()

        # test base query
        resp = self.client.get('/api/practitioner')
        self.assert200(resp)

        self.assertEqual(resp.json['total'], 3)
        self.assertEqual(resp.json['entry'][0]['name']['given'], 'Indiana')

        # test query with multiple results
        resp = self.client.get('/api/practitioner?first_name=John')
        self.assert200(resp)

        self.assertEqual(resp.json['total'], 2)
        self.assertEqual(resp.json['entry'][0]['name']['family'], 'Watson')

        # test query with multiple search parameters
        resp = self.client.get(
            '/api/practitioner?first_name=John&last_name=Zoidberg')
        self.assert200(resp)

        self.assertEqual(resp.json['total'], 1)
        self.assertEqual(resp.json['entry'][0]['name']['family'], 'Zoidberg')

        # test query using identifier system/value
        resp = self.client.get(
            '/api/practitioner?system=testsys&value=testval')
        self.assert200(resp)

        self.assertEqual(resp.json['total'], 1)
        self.assertEqual(resp.json['entry'][0]['name']['family'], 'Jones')

        # test invalid system/value combos
        resp = self.client.get(
            '/api/practitioner?system=testsys')
        self.assert400(resp)

        resp = self.client.get(
            '/api/practitioner?system=testsys&value=notvalid')
        self.assert404(resp)

    def test_practitioner_get(self):
        pract = Practitioner(first_name="Indiana", last_name="Jones",
                             phone='555-1234', email='test@notarealsite.com')
        pract2 = Practitioner(first_name="John", last_name="Watson")
        ident = Identifier(system='testsys', _value='testval')
        pract2.identifiers.append(ident)
        with SessionScope(db):
            db.session.add(pract)
            db.session.add(pract2)
            db.session.commit()
        pract = db.session.merge(pract)

        # test get by ID
        resp = self.client.get('/api/practitioner/{}'.format(pract.id))
        self.assert200(resp)

        self.assertEqual(resp.json['resourceType'], 'Practitioner')
        self.assertEqual(resp.json['name']['given'], 'Indiana')
        phone_json = {'system': 'phone', 'use': 'work', 'value': '555-1234'}
        self.assertTrue(phone_json in resp.json['telecom'])
        email_json = {'system': 'email', 'value': 'test@notarealsite.com'}
        self.assertTrue(email_json in resp.json['telecom'])

        # test get by external identifier
        resp = self.client.get(
            '/api/practitioner/{}?system={}'.format('testval', 'testsys'))
        self.assert200(resp)

        self.assertEqual(resp.json['resourceType'], 'Practitioner')
        self.assertEqual(resp.json['name']['family'], 'Watson')

        # test with invalid external identifier
        resp = self.client.get(
            '/api/practitioner/{}?system={}'.format('invalid', 'testsys'))
        self.assert404(resp)

    def test_practitioner_post(self):
        data = {
            'resourceType': 'Practitioner',
            'name': [
                {
                    'given': 'John',
                    'family': 'Zoidberg'
                }
            ],
            'telecom': [
                {
                    'system': 'phone',
                    'use': 'work',
                    'value': '555-1234'
                },
                {
                    'system': 'email',
                    'value': 'test@notarealsite.com'
                }
            ],
            'identifier': [
                {
                    'system': 'testsys',
                    'value': 'testval'
                }
            ]
        }

        self.promote_user(role_name=ROLE.ADMIN)
        self.login()

        resp = self.client.post('/api/practitioner', data=json.dumps(data),
                                content_type='application/json')
        self.assert200(resp)

        self.assertEqual(Practitioner.query.count(), 1)
        pract = Practitioner.query.all()[0]
        self.assertEqual(pract.last_name, 'Zoidberg')
        self.assertEqual(pract.email, 'test@notarealsite.com')
        self.assertEqual(pract.phone, '555-1234')
        self.assertEqual(len(pract.identifiers.all()), 1)
        self.assertEqual(pract.identifiers[0].system, 'testsys')

        # confirm audit entry for practitioner creation
        audit = Audit.query.first()
        audit_words = audit.comment.split()
        self.assertEqual(audit_words[0], 'created')

        # test with existing external identifier
        data = {
            'resourceType': 'Practitioner',
            'name': [
                {
                    'given': 'John',
                    'family': 'Watson'
                }
            ],
            'identifier': [
                {
                    'system': 'testsys',
                    'value': 'testval'
                }
            ]
        }

        resp = self.client.post('/api/practitioner', data=json.dumps(data),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 409)

    def test_practitioner_put(self):
        pract = Practitioner(first_name="John", last_name="Watson",
                             phone='555-1234', email='test1@notarealsite.com')
        pract2 = Practitioner(first_name="Indiana", last_name="Jones")
        ident = Identifier(system='testsys', _value='testval')
        pract2.identifiers.append(ident)
        with SessionScope(db):
            db.session.add(pract)
            db.session.add(pract2)
            db.session.commit()
        pract, pract2 = map(db.session.merge, (pract, pract2))
        pract_id = pract.id
        pract2_id = pract2.id

        data = {
            'resourceType': 'Practitioner',
            'name': [
                {
                    'given': 'John',
                    'family': 'Zoidberg'
                }
            ],
            'telecom': [
                {
                    'system': 'phone',
                    'use': 'work',
                    'value': '555-9876'
                },
                {
                    'system': 'email',
                    'value': 'test2@notarealsite.com'
                }
            ]
        }

        self.promote_user(role_name=ROLE.ADMIN)
        self.login()

        # test update by ID
        resp = self.client.put('/api/practitioner/{}'.format(pract_id),
                               data=json.dumps(data),
                               content_type='application/json')
        self.assert200(resp)

        updated = Practitioner.query.get(pract_id)
        self.assertEqual(updated.last_name, 'Zoidberg')
        self.assertEqual(updated.phone, '555-9876')
        self.assertEqual(updated.email, 'test2@notarealsite.com')

        # confirm audit entry for practitioner update
        audit = Audit.query.first()
        audit_words = audit.comment.split()
        self.assertEqual(audit_words[0], 'updated')

        # test update by external identifier
        data = {
            'resourceType': 'Practitioner',
            'telecom': [
                {
                    'system': 'phone',
                    'use': 'work',
                    'value': '999-9999'
                }
            ]
        }

        resp = self.client.put(
            '/api/practitioner/{}?system={}'.format('testval', 'testsys'),
            data=json.dumps(data),
            content_type='application/json')
        self.assert200(resp)

        updated = Practitioner.query.get(pract2_id)
        self.assertEqual(updated.last_name, 'Jones')
        self.assertEqual(updated.phone, '999-9999')

        # test with invalid external identifier
        resp = self.client.put(
            '/api/practitioner/{}?system={}'.format('invalid', 'testsys'),
            data=json.dumps(data),
            content_type='application/json')
        self.assert404(resp)

        # test with existing external identifier
        data = {
            'resourceType': 'Practitioner',
            'identifier': [
                {
                    'system': 'testsys',
                    'value': 'testval'
                }
            ]
        }

        resp = self.client.put('/api/practitioner/{}'.format(pract_id),
                               data=json.dumps(data),
                               content_type='application/json')
        self.assertEqual(resp.status_code, 409)
