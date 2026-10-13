"""Run from repo root: python -m unittest discover -s tests."""
import unittest
from fastapi.testclient import TestClient
from backend.app import app
from backend.knowledge_catalog import load_knowledge_products
from backend.reviewed_graph import build_plan


class PublicDemoTests(unittest.TestCase):
    def test_synthetic_catalog_and_graph(self):
        products = load_knowledge_products()
        self.assertEqual(len(products), 3)
        self.assertTrue(all(p['record_id'].startswith('demo-') for p in products))
        # Synthetic examples must never be published as authoritative product facts.
        with self.assertRaises(ValueError):
            build_plan()

    def test_public_routes_and_demo_query(self):
        client = TestClient(app)
        self.assertEqual(client.get('/').status_code, 200)
        self.assertEqual(client.get('/api/health').status_code, 200)
        response = client.post('/api/chat', json={
            'message': '介绍演示离心设备', 'session_id': 'public-demo-test'
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('演示离心设备', response.text)


if __name__ == '__main__':
    unittest.main()
