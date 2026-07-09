#!/usr/bin/env python3
"""
Test suite para ContractViewer.
10 tests unitarios para validar la logica del visualizador de contratos.
"""

import unittest
import tempfile
import shutil
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / 'execution'))

from dashboard.contract_viewer import ContractViewer


class TestContractViewerCore(unittest.TestCase):
    """Tests basicos del ContractViewer."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.viewer = ContractViewer(base_path=self.test_dir)
        self.contracts_dir = self.test_dir / 'memory' / 'contracts'
        self.contracts_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_list_contracts_empty(self):
        """Lista vacia cuando no hay contratos."""
        contracts = self.viewer.list_contracts()
        self.assertEqual(len(contracts), 0)

    def test_load_nonexistent_contract(self):
        """Carga contrato inexistente devuelve None."""
        result = self.viewer.load_contract('nonexistent')
        self.assertIsNone(result)


class TestContractViewerJSONL(unittest.TestCase):
    """Tests de lectura de archivos JSONL."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.viewer = ContractViewer(base_path=self.test_dir)
        self.contracts_dir = self.test_dir / 'memory' / 'contracts'
        self.contracts_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_read_single_contract(self):
        """Lee un contrato de un archivo JSONL."""
        contract_file = self.contracts_dir / '20260516.jsonl'
        contract = {
            'id': 'contract_001',
            'date': '2026-05-16T10:00:00Z',
            'agents': ['gemma', 'miguel'],
            'summary': 'Test contract',
            'status': 'active',
            'value': 1000
        }
        with open(contract_file, 'w', encoding='utf-8') as f:
            f.write(json.dumps(contract) + '\n')

        contracts = self.viewer.list_contracts()
        self.assertEqual(len(contracts), 1)
        self.assertEqual(contracts[0]['id'], 'contract_001')

    def test_read_multiple_contracts(self):
        """Lee multiples contratos."""
        contract_file = self.contracts_dir / '20260516.jsonl'
        contracts = [
            {'id': 'c001', 'date': '2026-05-16T10:00:00Z', 'agents': ['gemma'], 'summary': 'C1'},
            {'id': 'c002', 'date': '2026-05-16T11:00:00Z', 'agents': ['miguel'], 'summary': 'C2'}
        ]
        with open(contract_file, 'w', encoding='utf-8') as f:
            for c in contracts:
                f.write(json.dumps(c) + '\n')

        result = self.viewer.list_contracts(limit=10)
        self.assertEqual(len(result), 2)

    def test_contracts_sorted_by_date(self):
        """Contratos ordenados por fecha (reciente primero)."""
        contract_file = self.contracts_dir / '20260516.jsonl'
        contracts = [
            {'id': 'c001', 'date': '2026-05-15T10:00:00Z', 'agents': ['gemma'], 'summary': 'Old'},
            {'id': 'c002', 'date': '2026-05-16T10:00:00Z', 'agents': ['gemma'], 'summary': 'New'}
        ]
        with open(contract_file, 'w', encoding='utf-8') as f:
            for c in contracts:
                f.write(json.dumps(c) + '\n')

        result = self.viewer.list_contracts()
        self.assertEqual(result[0]['id'], 'c002')
        self.assertEqual(result[1]['id'], 'c001')


class TestContractViewerFilter(unittest.TestCase):
    """Tests de filtrado por agente."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.viewer = ContractViewer(base_path=self.test_dir)
        self.contracts_dir = self.test_dir / 'memory' / 'contracts'
        self.contracts_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_filter_by_agent(self):
        """Filtra contratos por agente."""
        contract_file = self.contracts_dir / '20260516.jsonl'
        contracts = [
            {'id': 'c001', 'date': '2026-05-16T10:00:00Z', 'agents': ['gemma'], 'summary': 'Gemma contract'},
            {'id': 'c002', 'date': '2026-05-16T11:00:00Z', 'agents': ['miguel'], 'summary': 'Miguel contract'}
        ]
        with open(contract_file, 'w', encoding='utf-8') as f:
            for c in contracts:
                f.write(json.dumps(c) + '\n')

        result = self.viewer.list_contracts(agent_id='gemma')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], 'c001')

    def test_get_agents_in_contracts(self):
        """Lista agentes unicos en contratos."""
        contract_file = self.contracts_dir / '20260516.jsonl'
        contracts = [
            {'id': 'c001', 'date': '2026-05-16T10:00:00Z', 'agents': ['gemma', 'miguel'], 'summary': 'Both'},
        ]
        with open(contract_file, 'w', encoding='utf-8') as f:
            for c in contracts:
                f.write(json.dumps(c) + '\n')

        agents = self.viewer.get_agents_in_contracts()
        self.assertIn('gemma', agents)
        self.assertIn('miguel', agents)


class TestContractViewerRender(unittest.TestCase):
    """Tests de renderizado."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.viewer = ContractViewer(base_path=self.test_dir)
        self.contracts_dir = self.test_dir / 'memory' / 'contracts'
        self.contracts_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_render_summary_empty(self):
        """Renderiza resumen vacio."""
        result = self.viewer.render_summary()
        self.assertIn('No hay contratos', result)

    def test_render_summary_with_data(self):
        """Renderiza resumen con contratos."""
        contract_file = self.contracts_dir / '20260516.jsonl'
        contract = {
            'id': 'contract_001',
            'date': '2026-05-16T10:00:00Z',
            'agents': ['gemma'],
            'summary': 'Test',
            'status': 'active',
            'value': 1000
        }
        with open(contract_file, 'w', encoding='utf-8') as f:
            f.write(json.dumps(contract) + '\n')

        result = self.viewer.render_summary()
        self.assertIn('contract_001', result)
        self.assertIn('gemma', result)

    def test_render_contract_detail(self):
        """Renderiza detalle de contrato."""
        contract_file = self.contracts_dir / '20260516.jsonl'
        contract = {
            'id': 'contract_001',
            'date': '2026-05-16T10:00:00Z',
            'agents': ['gemma'],
            'summary': 'Test contract',
            'status': 'active',
            'value': 1000,
            'terms': 'Test terms',
            'metadata': {}
        }
        with open(contract_file, 'w', encoding='utf-8') as f:
            f.write(json.dumps(contract) + '\n')

        result = self.viewer.render_contract_detail('contract_001')
        self.assertIn('contract_001', result)
        self.assertIn('Test contract', result)

    def test_render_nonexistent_contract(self):
        """Renderiza error para contrato inexistente."""
        result = self.viewer.render_contract_detail('nonexistent')
        self.assertIn('ERROR', result)


if __name__ == '__main__':
    unittest.main()