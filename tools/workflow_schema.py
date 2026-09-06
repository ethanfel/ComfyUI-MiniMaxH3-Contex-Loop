"""Offline release-workflow contracts. Local H3 definitions are authoritative.

External contracts are a sanitized snapshot: no local model/media inventory.
This imports schema methods only; it never loads weights or starts ComfyUI.
Run as a standalone tooling process because ComfyUI imports are stubbed.
"""
from __future__ import annotations

import copy
import importlib
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'tools' / 'v06'
PRIMITIVES = {'INT', 'FLOAT', 'STRING', 'BOOLEAN', 'COMBO'}


def load_schemas():
    package_name = '_h3_release_workflow_schema'
    package = types.ModuleType(package_name)
    package.__path__ = [str(ROOT)]
    sys.modules[package_name] = package
    folder_paths = types.ModuleType('folder_paths')
    for name in ('get_output_directory', 'get_temp_directory', 'get_input_directory'):
        setattr(folder_paths, name, lambda: str(ROOT))
    folder_paths.get_annotated_filepath = lambda value: str(value)
    sys.modules['folder_paths'] = folder_paths
    for name in ('comfy', 'comfy.utils', 'comfy.ldm', 'comfy.ldm.minimax',
                 'comfy.ldm.minimax.model', 'comfy.model_base', 'node_helpers'):
        sys.modules.setdefault(name, types.ModuleType(name))
        if '.' in name:
            parent, child = name.rsplit('.', 1)
            setattr(sys.modules[parent], child, sys.modules[name])
    classes = {}
    for module, mapping in (
            ('nodes', 'NODE_CLASS_MAPPINGS'),
            ('chain_nodes', 'CHAIN_NODE_CLASS_MAPPINGS'),
            ('upscale_nodes', 'UPSCALE_NODE_CLASS_MAPPINGS'),
            ('masking_nodes', 'NODE_CLASS_MAPPINGS'),
            ('masked_bridge', 'NODE_CLASS_MAPPINGS'),
            ('source_av_target', 'NODE_CLASS_MAPPINGS')):
        imported = importlib.import_module(package_name + '.' + module)
        classes.update(getattr(imported, mapping))
    schemas = json.loads((DATA / 'external_schemas.json').read_text())['nodes']
    for name, cls in classes.items():
        inputs = cls.INPUT_TYPES()
        schemas[name] = {
            'input': inputs, 'output': list(cls.RETURN_TYPES),
            'output_name': list(getattr(cls, 'RETURN_NAMES', cls.RETURN_TYPES)),
            'output_is_list': list(getattr(cls, 'OUTPUT_IS_LIST', [False]*len(cls.RETURN_TYPES))),
        }
    # Match /object_info serialization, including wildcard str subclasses whose
    # overloaded comparisons must not be used as schema-type comparisons.
    return json.loads(json.dumps(schemas))


def fields(schema):
    return {**schema['input'].get('required', {}), **schema['input'].get('optional', {})}


def options(spec):
    return spec[1] if len(spec) > 1 else {}


def is_widget(spec):
    return (isinstance(spec[0], (list, tuple)) or spec[0] in PRIMITIVES
            or spec[0] == 'COMFY_DYNAMICCOMBO_V3') and not options(spec).get('forceInput')


def choices(spec):
    if isinstance(spec[0], (list, tuple)):
        return list(spec[0])
    return options(spec).get('options') if spec[0] == 'COMBO' else None


def default(spec):
    opts = options(spec)
    if 'default' in opts:
        return copy.deepcopy(opts['default'])
    values = choices(spec)
    if values:
        return values[0]
    return {'STRING':'', 'BOOLEAN':False, 'INT':0, 'FLOAT':0.0}.get(spec[0], '')


def widget_fields(schema, values):
    """Include converted widgets, control-after-generate and V3 dynamic children."""
    for name, spec in fields(schema).items():
        if not is_widget(spec):
            continue
        if spec[0] == 'COMFY_DYNAMICCOMBO_V3':
            variants = options(spec)['options']
            yield name, [[v['key'] for v in variants], {}]
            chosen = values.get(name, variants[0]['key'])
            variant = next(v for v in variants if v['key'] == chosen)
            for child, child_spec in widget_fields({'input':variant['inputs']}, values):
                yield name + '.' + child, child_spec
        else:
            yield name, spec
            if options(spec).get('control_after_generate') or name in ('seed', 'noise_seed'):
                yield 'control_after_generate', [['fixed', 'increment', 'decrement', 'randomize'], {'default':'fixed'}]


def validate_value(value, spec, label):
    kind, opts = spec[0], options(spec)
    values = choices(spec)
    if values is not None:
        assert value in values, (label, value, 'not in allowed choices', values)
    elif kind == 'INT':
        assert isinstance(value, int) and not isinstance(value, bool), (label, value, 'expected integer')
    elif kind == 'FLOAT':
        assert isinstance(value, (int, float)) and not isinstance(value, bool), (label, value, 'expected number')
    elif kind == 'BOOLEAN':
        assert isinstance(value, bool), (label, value, 'expected boolean')
    elif kind == 'STRING':
        assert isinstance(value, str), (label, value, 'expected string')
    if kind in ('INT', 'FLOAT') and isinstance(value, (int, float)):
        assert opts.get('min', float('-inf')) <= value <= opts.get('max', float('inf')), (label, value, 'out of range')
