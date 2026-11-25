import copy
from unittest.mock import patch
from django.test import TestCase, override_settings
from .models import Binding, CurrentState, Gateway
from habitat.models import Enclosure, Store, User


@override_settings(SECURE_SSL_REDIRECT=False, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SpatialTests(TestCase):
    def setUp(self):
        self.store = Store.objects.create(name='공간 검증')
        self.cage = Enclosure.objects.create(id='507a8d53-a6b1-49d7-aab3-1becba7a0451', name='공간 검증', store=self.store, edge_cage_id='CAGE-001')
        self.gateway = Gateway.objects.create(store=self.store, edge_gateway_id='PI-001', token_digest='spatial-test-only')
        Binding.objects.create(enclosure=self.cage, gateway=self.gateway)
        self.state = CurrentState.objects.create(enclosure=self.cage, configuration={'geometry_revision': 1, 'placement_revision': 1, 'sensors': [{'id': x, 'unit': 'degC'} for x in ('T1', 'T2', 'T3')]})
        self.owner = User.objects.create_user(username='spatial-owner', display_name='검증', role='owner')
        self.client.force_login(self.owner)

    def layout(self):
        return self.client.get(f'/api/enclosures/{self.cage.pk}/').json()['item'].get('spatialLayout')

    def test_registered_layout_contains_units_and_assumption_provenance(self):
        layout = self.layout()
        self.assertIsNotNone(layout)
        self.assertEqual(layout['dimensionsCm'], [20, 20, 30])
        self.assertEqual(layout['sensors'][0]['positionCm'], [10, 10, 28])
        self.assertFalse(layout['positionsVerified'])
        self.assertIn('Pi', layout['source'])

    def test_registered_layout_is_scoped_to_cage002(self):
        cage = Enclosure.objects.create(
            id='ef17c3f7-329b-4b14-8be4-b720c8666e31',
            name='크레스티드 게코 사육장',
            store=self.store,
            edge_cage_id='CAGE-002',
        )
        Binding.objects.create(enclosure=cage, gateway=self.gateway)
        CurrentState.objects.create(
            enclosure=cage,
            configuration={
                'geometry_revision': 1,
                'placement_revision': 1,
                'sensors': [{'id': sensor, 'unit': 'degC'} for sensor in ('T1', 'T2', 'T3')],
            },
        )
        layout = self.client.get(f'/api/enclosures/{cage.pk}/').json()['item'].get('spatialLayout')
        self.assertEqual(layout['id'], 'cage002-presentation-assumed-v1')
        self.assertFalse(layout['positionsVerified'])
        self.assertEqual(layout['source'], '등록 센서 배치')

    def test_layout_not_reused_after_revision_sensor_unit_or_gateway_change(self):
        original = copy.deepcopy(self.state.configuration)
        for config in ({**original, 'placement_revision': 2}, {**original, 'geometry_revision': 2}, {**original, 'sensors': [{'id': 'T1', 'unit': 'percent_rh'}]}):
            self.state.configuration = config
            self.state.save()
            self.assertIsNone(self.layout())
        self.state.configuration = original
        self.state.save()
        self.gateway.edge_gateway_id = 'OTHER'
        self.gateway.save()
        self.assertIsNone(self.layout())

    def test_other_enclosure_has_no_invented_layout_and_access_stays_scoped(self):
        other = Enclosure.objects.create(id='other', name='다른 사육장', store=self.store)
        self.assertIsNone(self.client.get('/api/enclosures/other/').json()['item'].get('spatialLayout'))
        user = User.objects.create_user(username='spatial-user', display_name='검증', role='user', store=self.store)
        self.client.force_login(user)
        self.assertEqual(self.client.get(f'/api/enclosures/{self.cage.pk}/').status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(f'/api/enclosures/{self.cage.pk}/').status_code, 401)
