# Add root folder to python paths
# This must be done on every test in order to pass in Travis
import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.realpath(os.path.join(script_dir, '..', '..', '..')))
sys._called_from_test = True  # need db open for tests (see eos/config.py)

# This import is here to hack around circular import issues
import pytest
import gui.mainFrame
from service.speedBreakdown import get_speed_breakdown


def test_get_speed_breakdown_NoneFit():
    result = get_speed_breakdown(None)
    assert result is not None
    assert result['speedNoPropNoBoost'] is None
    assert result['speedNoPropWithBoost'] is None
    assert result['speedWithPropNoBoost'] is None
    assert result['speedWithPropWithBoost'] is None
    assert result['lockRangeNoBoost'] is None
    assert result['lockRangeWithBoost'] is None
    assert result['fittedPropLabel'] is None
    assert result['speedWithABNoBoost'] is None
    assert result['speedWithABWithBoost'] is None
    assert result['speedWithMWDNoBoost'] is None
    assert result['speedWithMWDWithBoost'] is None
    assert result['cargoPropRows'] == []


def test_get_speed_breakdown_ResultStructure():
    """Sanity check: EFT import produces fit; get_speed_breakdown returns expected keys and types."""
    from service.port import Port
    eft_lines = """[Rifter, Rifter No Prop]
200mm Autocannon II, EMP S
200mm Autocannon II, EMP S
200mm Autocannon II, EMP S
"""
    fit = Port.importEft(eft_lines.splitlines())
    assert fit is not None
    result = get_speed_breakdown(fit)
    required_keys = {
        'speedNoPropNoBoost', 'speedNoPropWithBoost',
        'speedWithPropNoBoost', 'speedWithPropWithBoost',
        'speedWithABNoBoost', 'speedWithABWithBoost',
        'speedWithMWDNoBoost', 'speedWithMWDWithBoost',
        'lockRangeNoBoost', 'lockRangeWithBoost',
        'fittedPropLabel', 'cargoPropRows',
    }
    assert required_keys.issubset(result.keys())
    for key in ('speedNoPropNoBoost', 'speedNoPropWithBoost', 'speedWithPropNoBoost', 'speedWithPropWithBoost'):
        v = result[key]
        assert v is None or isinstance(v, (int, float))
    for key in ('lockRangeNoBoost', 'lockRangeWithBoost'):
        v = result[key]
        assert v is None or isinstance(v, (int, float))
    assert result['fittedPropLabel'] is None or isinstance(result['fittedPropLabel'], str)
    assert isinstance(result['cargoPropRows'], list)
    for row in result['cargoPropRows']:
        assert 'name' in row and 'propType' in row
        assert row['propType'] in ('Afterburner', 'Microwarpdrive', 'Propulsion')


def test_get_speed_breakdown_WithPropMod():
    """Fit with propulsion module: with-prop and no-prop speeds can differ."""
    from service.port import Port
    eft_lines = """[Rifter, Rifter AB]
1MN Afterburner II
200mm Autocannon II, EMP S
200mm Autocannon II, EMP S
200mm Autocannon II, EMP S
"""
    fit = Port.importEft(eft_lines.splitlines())
    assert fit is not None
    result = get_speed_breakdown(fit)
    # With prop should be higher than no-prop (AB adds speed)
    no_prop = result['speedNoPropWithBoost']
    with_prop = result['speedWithPropWithBoost']
    assert no_prop is not None and with_prop is not None
    assert with_prop > no_prop
    # Fitted prop label should identify Afterburner
    assert result['fittedPropLabel'] is not None
    assert 'Afterburner' in result['fittedPropLabel']


def test_get_speed_breakdown_NoPropMod():
    """Fit without propulsion: no-prop and with-prop speeds are the same."""
    from service.port import Port
    eft_lines = """[Rifter, Rifter No Prop]
200mm Autocannon II, EMP S
200mm Autocannon II, EMP S
200mm Autocannon II, EMP S
"""
    fit = Port.importEft(eft_lines.splitlines())
    assert fit is not None
    result = get_speed_breakdown(fit)
    assert result['speedNoPropWithBoost'] == result['speedWithPropWithBoost']
    assert result['speedNoPropNoBoost'] == result['speedWithPropNoBoost']
    assert result['fittedPropLabel'] is None


def test_get_speed_breakdown_LockRangePresent():
    """Lock range values are numeric when fit has ship."""
    from service.port import Port
    eft_lines = """[Rifter, Rifter]
200mm Autocannon II, EMP S
200mm Autocannon II, EMP S
200mm Autocannon II, EMP S
"""
    fit = Port.importEft(eft_lines.splitlines())
    assert fit is not None
    result = get_speed_breakdown(fit)
    assert result['lockRangeNoBoost'] is not None
    assert result['lockRangeWithBoost'] is not None
    assert result['lockRangeNoBoost'] > 0
    assert result['lockRangeWithBoost'] > 0
