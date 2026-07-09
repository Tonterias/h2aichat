#!/usr/bin/env python3
"""
Test suite para AgentEditor.
10 tests unitarios para validar la logica del editor de agentes.
"""

import unittest
import tempfile
import shutil
from pathlib import Path
import sys
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard.agent_editor import AgentEditor


class TestAgentEditorCore(unittest.TestCase):
    """Tests basicos del AgentEditor."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.editor = AgentEditor(base_path=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_list_agents_empty(self):
        """Lista agentes vacia cuando no hay configs."""
        agents = self.editor.list_agents()
        self.assertEqual(len(agents), 0)

    def test_create_default_config(self):
        """Crea config default para un agente."""
        config = self.editor._create_default_config('test_agent')

        self.assertEqual(config['agent_id'], 'test_agent')
        self.assertEqual(config['type'], 'bot')
        self.assertEqual(config['role'], 'ai_agent')
        self.assertIn('llm_config', config)
        self.assertIn('system_prompt', config)
        self.assertIn('metadata', config)

    def test_load_nonexistent_agent_creates_default(self):
        """Carga agente inexistente devuelve config default."""
        config = self.editor.load_agent_config('new_agent')

        self.assertEqual(config['agent_id'], 'new_agent')
        self.assertEqual(config['type'], 'bot')


class TestAgentEditorPersistence(unittest.TestCase):
    """Tests de persistencia (carga/guardado)."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.editor = AgentEditor(base_path=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_save_and_load_agent_config(self):
        """Guarda y carga config correctamente."""
        config = self.editor._create_default_config('gemma')
        config['system_prompt'] = 'Test prompt for gemma'

        success, msg = self.editor.save_agent_config('gemma', config)
        self.assertTrue(success)

        loaded = self.editor.load_agent_config('gemma')
        self.assertEqual(loaded['agent_id'], 'gemma')
        self.assertEqual(loaded['system_prompt'], 'Test prompt for gemma')

    def test_atomic_write_creates_temp_file(self):
        """Escritura atomica usa archivo temporal."""
        config = self.editor._create_default_config('atomic_test')
        self.editor.save_agent_config('atomic_test', config)

        tmp_files = list(self.test_dir.glob('**/*.tmp'))
        self.assertEqual(len(tmp_files), 0)

    def test_overwrite_existing_config(self):
        """Sobrescribe config existente."""
        config1 = self.editor._create_default_config('overwrite')
        config1['system_prompt'] = 'Original prompt'

        self.editor.save_agent_config('overwrite', config1)

        config2 = self.editor.load_agent_config('overwrite')
        config2['system_prompt'] = 'Updated prompt'

        success, _ = self.editor.save_agent_config('overwrite', config2)
        self.assertTrue(success)

        final = self.editor.load_agent_config('overwrite')
        self.assertEqual(final['system_prompt'], 'Updated prompt')


class TestAgentEditorValidation(unittest.TestCase):
    """Tests de validacion de configuracion."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.editor = AgentEditor(base_path=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_validate_valid_config(self):
        """Valida config correcta."""
        config = self.editor._create_default_config('valid')
        is_valid, errors = self.editor.validate_config(config)
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)

    def test_validate_invalid_temperature(self):
        """Rechaza temperature fuera de rango."""
        config = self.editor._create_default_config('invalid_temp')
        config['llm_config']['temperature'] = 5.0

        is_valid, errors = self.editor.validate_config(config)
        self.assertFalse(is_valid)
        self.assertTrue(any('temperature' in e for e in errors))

    def test_validate_invalid_max_tokens(self):
        """Rechaza max_tokens fuera de rango."""
        config = self.editor._create_default_config('invalid_tokens')
        config['llm_config']['max_tokens'] = 10000

        is_valid, errors = self.editor.validate_config(config)
        self.assertFalse(is_valid)
        self.assertTrue(any('max_tokens' in e for e in errors))

    def test_validate_invalid_model(self):
        """Rechaza modelo no permitido."""
        config = self.editor._create_default_config('invalid_model')
        config['llm_config']['model'] = 'invalid/model-name'

        is_valid, errors = self.editor.validate_config(config)
        self.assertFalse(is_valid)
        self.assertTrue(any('model' in e for e in errors))

    def test_validate_short_system_prompt(self):
        """Rechaza system prompt muy corto."""
        config = self.editor._create_default_config('short_prompt')
        config['system_prompt'] = 'Hi'

        is_valid, errors = self.editor.validate_config(config)
        self.assertFalse(is_valid)
        self.assertTrue(any('system_prompt' in e for e in errors))

    def test_validate_invalid_agent_id(self):
        """Rechaza agent_id con caracteres invalidos."""
        config = self.editor._create_default_config('invalid-id')
        config['agent_id'] = 'invalid/id:with/slashes'

        is_valid, errors = self.editor.validate_config(config)
        self.assertFalse(is_valid)
        self.assertTrue(any('agent_id' in e for e in errors))


class TestAgentEditorSanitization(unittest.TestCase):
    """Tests de sanitizacion y seguridad."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.editor = AgentEditor(base_path=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_sanitize_removes_code_blocks(self):
        """Elimina bloques de codigo markdown."""
        prompt = "Texto normal\n```python\nimport os\n```\nMas texto"
        sanitized = self.editor.sanitize_prompt(prompt)

        self.assertNotIn('```', sanitized)
        self.assertIn('Texto normal', sanitized)
        self.assertIn('Mas texto', sanitized)

    def test_sanitize_removes_excessive_newlines(self):
        """Elimina saltos de linea multiples."""
        prompt = "Linea 1\n\n\n\n\nLinea 2"
        sanitized = self.editor.sanitize_prompt(prompt)

        self.assertEqual(sanitized.count('\n'), 2)

    def test_yaml_injection_prevention(self):
        """Previene injection de YAML en campos."""
        config = {
            'agent_id': 'test',
            'system_prompt': '---malicious yaml',
            'llm_config': {'temperature': 0.5, 'max_tokens': 512, 'model': 'local-model'}
        }

        is_safe = self.editor.validate_no_yaml_injection(config)
        self.assertFalse(is_safe)

    def test_safe_config_passes_injection_check(self):
        """Config segura pasa validacion de injection."""
        config = self.editor._create_default_config('safe')
        is_safe = self.editor.validate_no_yaml_injection(config)
        self.assertTrue(is_safe)


class TestAgentEditorBuffer(unittest.TestCase):
    """Tests del buffer de edicion."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.editor = AgentEditor(base_path=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_start_edit_loads_buffer(self):
        """start_edit carga config en buffer."""
        config = self.editor._create_default_config('buffer_test')
        self.editor.save_agent_config('buffer_test', config)

        form = self.editor.start_edit('buffer_test')

        self.assertIn('buffer_test', form)
        self.assertIn('EDITANDO', form)

    def test_update_system_prompt_in_buffer(self):
        """Actualiza system prompt en buffer."""
        self.editor.start_edit('prompt_test')
        success, msg = self.editor.update_system_prompt('prompt_test', 'New prompt for testing')

        self.assertTrue(success)
        self.assertIn('prompt_test', self.editor._edit_buffer)

    def test_update_temperature_in_buffer(self):
        """Actualiza temperature en buffer."""
        self.editor.start_edit('temp_test')
        success, msg = self.editor.update_temperature('temp_test', '0.8')

        self.assertTrue(success)
        self.assertEqual(self.editor._edit_buffer['temp_test']['llm_config']['temperature'], 0.8)

    def test_discard_clears_buffer(self):
        """discard_changes limpia el buffer."""
        self.editor.start_edit('discard_test')
        result = self.editor.discard_changes('discard_test')

        self.assertTrue(result)
        self.assertNotIn('discard_test', self.editor._edit_buffer)


if __name__ == '__main__':
    unittest.main()