# =============================================================================
# Copyright (C) 2010 Diego Duclos
#
# This file is part of pyfa.
#
# pyfa is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# pyfa is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with pyfa.  If not, see <http://www.gnu.org/licenses/>.
# =============================================================================

from eos.const import FittingSlot
from eos.saveddata.module import Module
from service.fit import Fit


def _prop_type_str(item):
    """Return 'Afterburner', 'Microwarpdrive', or 'Propulsion' for a propulsion module item."""
    if item is None:
        return 'Propulsion'
    try:
        if item.requiresSkill('Afterburner'):
            return 'Afterburner'
        if item.requiresSkill('High Speed Maneuvering'):
            return 'Microwarpdrive'
    except Exception:
        pass
    return 'Propulsion'


def _get_propulsion_modules(fit):
    """Return list of fitted modules that are propulsion (AB/MWD)."""
    if fit is None:
        return []
    return [
        m for m in fit.modules
        if getattr(m.item, 'group', None) and m.item.group.name == 'Propulsion Module'
    ]


def _get_speed_with_limit(fit):
    """Return current max speed (m/s), respecting speedLimit if set."""
    if fit is None or fit.ship is None:
        return None
    speed_limit = fit.ship.getModifiedItemAttr('speedLimit')
    max_vel = fit.ship.getModifiedItemAttr('maxVelocity')
    if max_vel is None:
        return None
    if speed_limit and max_vel > speed_limit:
        return speed_limit
    return max_vel


def _get_speed_without_prop(fit, prop_modules):
    """Return max speed (m/s) as if prop modules were not fitted."""
    if fit is None or fit.ship is None:
        return None
    if not prop_modules:
        return _get_speed_with_limit(fit)
    max_vel = fit.ship.getModifiedItemAttrExtended(
        'maxVelocity', ignoreAfflictors=tuple(prop_modules)
    )
    if max_vel is None:
        return None
    speed_limit = fit.ship.getModifiedItemAttr('speedLimit')
    if speed_limit and max_vel > speed_limit:
        return speed_limit
    return max_vel


def _get_lock_range(fit):
    """Return max targeting range (same unit as game, typically meters)."""
    if fit is None or fit.ship is None:
        return None
    return fit.ship.getModifiedItemAttr('maxTargetRange')


def _get_propulsion_items_in_cargo(fit):
    """Return distinct propulsion module items in fit.cargo (by item ID)."""
    if fit is None or not fit.cargo:
        return []
    seen = set()
    result = []
    for c in fit.cargo:
        if c.item is None:
            continue
        group = getattr(c.item, 'group', None)
        if group is None or group.name != 'Propulsion Module':
            continue
        if c.item.ID in seen:
            continue
        seen.add(c.item.ID)
        result.append(c.item)
    return result


def _get_command_links_snapshot(fit):
    """Return list of (commandInfo, active) for all command links applying to this fit (no state change)."""
    snapshot = []
    for cmd_fit in fit.commandFits:
        info = cmd_fit.getCommandInfo(fit.ID)
        if info is None:
            continue
        snapshot.append((info, info.active))
    return snapshot


def _set_command_links_active(fit, active):
    """
    Set active state for all command links that apply to this fit.
    Returns list of (commandInfo, previous_active) for restore.
    """
    snapshot = []
    for cmd_fit in fit.commandFits:
        info = cmd_fit.getCommandInfo(fit.ID)
        if info is None:
            continue
        snapshot.append((info, info.active))
        info.active = active
    return snapshot


def _restore_command_links(snapshot):
    """Restore command link active states from _set_command_links_active snapshot."""
    for info, was_active in snapshot:
        info.active = was_active


def _recalc_without_fleet_boosts(fit):
    """
    Temporarily turn all command links off (active=False), recalc so no gang boosts are applied,
    then return snapshot for restore. Caller must _restore_command_links(snapshot) and recalc.
    """
    snapshot = _set_command_links_active(fit, False)
    fit.calculated = False
    fit.calculateModifiedAttributes()
    return snapshot


def _simulate_speed_with_cargo_prop(fit, item, sFit, replace_index=None):
    """
    Temporarily fit the given propulsion item from cargo, read speed with/without fleet boost
    (command all on / command all off), then restore fit.
    Returns (speed_no_boost, speed_with_boost) or (None, None) on failure.
    If replace_index is None, requires an empty mid slot (append). If replace_index is int,
    temporarily replaces the module at that index (for when prop is fitted but we want other type from cargo).
    """
    try:
        temp_module = Module(item)
    except Exception:
        return None, None
    if replace_index is not None:
        try:
            original_mod = fit.modules[replace_index]
        except IndexError:
            return None, None
        fit.modules.replace(replace_index, temp_module)
        if temp_module.isInvalid:
            fit.modules.replace(replace_index, original_mod)
            return None, None
    else:
        fit.modules.append(temp_module)
        if temp_module not in fit.modules:
            return None, None
        original_mod = None
    # Save command link state so we can restore at the end
    links_snapshot = _get_command_links_snapshot(fit)
    try:
        # With boost = command all ON
        _set_command_links_active(fit, True)
        fit.calculated = False
        fit.calculateModifiedAttributes()
        if replace_index is not None and (temp_module.isInvalid or fit.modules[replace_index] is not temp_module):
            return None, None
        speed_with_boost = _get_speed_with_limit(fit)
        # Without boost = command all OFF
        _recalc_without_fleet_boosts(fit)
        speed_no_boost = _get_speed_with_limit(fit)
        return speed_no_boost, speed_with_boost
    finally:
        _restore_command_links(links_snapshot)
        if replace_index is not None:
            fit.modules.replace(replace_index, original_mod)
        else:
            fit.modules.remove(temp_module)
            fit.fill()
        fit.calculated = False
        fit.calculateModifiedAttributes()


def get_speed_breakdown(fit):
    """
    Compute speed (with/without prop mod, with/without fleet boosts) and lock range
    (with/without fleet boosts). If the fit has propulsion modules in cargo, also
    compute one row per distinct cargo prop type (speed and lock with/without boosts)
    by temporarily fitting that module when an empty mid slot exists.

    Returns a dict with:
      - speedNoPropNoBoost, speedNoPropWithBoost, speedWithPropNoBoost, speedWithPropWithBoost (float m/s or None)
      - lockRangeNoBoost, lockRangeWithBoost (float or None)
      - cargoPropRows: list of dicts with name, speedNoBoost, speedWithBoost, lockRangeNoBoost, lockRangeWithBoost
    """
    if fit is None:
        return {
            'speedNoPropNoBoost': None,
            'speedNoPropWithBoost': None,
            'speedWithPropNoBoost': None,
            'speedWithPropWithBoost': None,
            'speedWithABNoBoost': None,
            'speedWithABWithBoost': None,
            'speedWithMWDNoBoost': None,
            'speedWithMWDWithBoost': None,
            'lockRangeNoBoost': None,
            'lockRangeWithBoost': None,
            'fittedPropLabel': None,
            'cargoPropRows': [],
        }

    sFit = Fit.getInstance()
    prop_modules = _get_propulsion_modules(fit)
    # Label for fitted prop: "ItemName (Afterburner)" or "ItemName (Microwarpdrive)", or None
    if prop_modules:
        first_prop = prop_modules[0]
        ptype = _prop_type_str(first_prop.item)
        fitted_prop_label = '{} ({})'.format(first_prop.item.name, ptype)
    else:
        fitted_prop_label = None

    # With boost = command all ON; without boost = command all OFF (ignore current toggle state)
    original_links_snapshot = _get_command_links_snapshot(fit)

    # First: set all command links ON, recalc, read "with boost" values
    _set_command_links_active(fit, True)
    fit.calculated = False
    fit.calculateModifiedAttributes()
    speed_with_prop_with_boost = _get_speed_with_limit(fit)
    speed_no_prop_with_boost = _get_speed_without_prop(fit, prop_modules)
    lock_range_with_boost = _get_lock_range(fit)

    # Second: set all command links OFF, recalc, read "without boost" values
    _recalc_without_fleet_boosts(fit)  # sets all to False and recalc
    speed_with_prop_no_boost = _get_speed_with_limit(fit)
    speed_no_prop_no_boost = _get_speed_without_prop(fit, prop_modules)
    lock_range_no_boost = _get_lock_range(fit)

    # Restore original command link states and recalc so fit is back to normal
    _restore_command_links(original_links_snapshot)
    fit.calculated = False
    fit.calculateModifiedAttributes()

    # AB/MWD speeds for table: use fitted prop when present, else simulate from cargo if possible
    speed_ab_no_boost = None
    speed_ab_with_boost = None
    speed_mwd_no_boost = None
    speed_mwd_with_boost = None
    if prop_modules:
        first_ptype = _prop_type_str(prop_modules[0].item)
        if first_ptype == 'Afterburner':
            speed_ab_no_boost = speed_with_prop_no_boost
            speed_ab_with_boost = speed_with_prop_with_boost
        elif first_ptype == 'Microwarpdrive':
            speed_mwd_no_boost = speed_with_prop_no_boost
            speed_mwd_with_boost = speed_with_prop_with_boost

    # If AB or MWD not from fitted, try first matching type in cargo (empty mid or replace fitted prop)
    cargo_prop_items = _get_propulsion_items_in_cargo(fit)
    has_empty_mid = fit.getSlotsFree(FittingSlot.MED) > 0
    prop_replace_index = None  # index of fitted prop to temporarily replace (when no empty mid)
    if prop_modules and not has_empty_mid:
        for idx, mod in enumerate(fit.modules):
            if getattr(mod.item, 'group', None) and mod.item.group.name == 'Propulsion Module':
                prop_replace_index = idx
                break
    for item in cargo_prop_items:
        ptype = _prop_type_str(item)
        if ptype == 'Afterburner' and speed_ab_no_boost is None and speed_ab_with_boost is None:
            idx = prop_replace_index if not has_empty_mid else None
            speed_ab_no_boost, speed_ab_with_boost = _simulate_speed_with_cargo_prop(fit, item, sFit, replace_index=idx)
            break
    for item in cargo_prop_items:
        ptype = _prop_type_str(item)
        if ptype == 'Microwarpdrive' and speed_mwd_no_boost is None and speed_mwd_with_boost is None:
            idx = prop_replace_index if not has_empty_mid else None
            speed_mwd_no_boost, speed_mwd_with_boost = _simulate_speed_with_cargo_prop(fit, item, sFit, replace_index=idx)
            break

    # Cargo propulsion: list distinct prop items in cargo with type (AB/MWD) only
    cargo_prop_rows = []
    for item in _get_propulsion_items_in_cargo(fit):
        cargo_prop_rows.append({
            'name': item.name,
            'propType': _prop_type_str(item),
        })

    # Final restore so the fit is in correct state
    sFit.recalc(fit)

    return {
        'speedNoPropNoBoost': speed_no_prop_no_boost,
        'speedNoPropWithBoost': speed_no_prop_with_boost,
        'speedWithPropNoBoost': speed_with_prop_no_boost,
        'speedWithPropWithBoost': speed_with_prop_with_boost,
        'speedWithABNoBoost': speed_ab_no_boost,
        'speedWithABWithBoost': speed_ab_with_boost,
        'speedWithMWDNoBoost': speed_mwd_no_boost,
        'speedWithMWDWithBoost': speed_mwd_with_boost,
        'lockRangeNoBoost': lock_range_no_boost,
        'lockRangeWithBoost': lock_range_with_boost,
        'fittedPropLabel': fitted_prop_label,
        'cargoPropRows': cargo_prop_rows,
    }
