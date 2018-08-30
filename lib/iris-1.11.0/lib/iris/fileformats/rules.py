# (C) British Crown Copyright 2010 - 2016, Met Office
#
# This file is part of Iris.
#
# Iris is free software: you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the
# Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Iris is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Iris.  If not, see <http://www.gnu.org/licenses/>.
"""
Generalised mechanisms for metadata translation and cube construction.

"""

from __future__ import (absolute_import, division, print_function)
from six.moves import (filter, input, map, range, zip)  # noqa
import six

import abc
import collections
from contextlib import contextmanager
import getpass
import logging
import logging.handlers as handlers
import os
import os.path
import platform
import sys
import types
import warnings

import cf_units
import numpy as np
import numpy.ma as ma

from iris._deprecation import warn_deprecated
from iris.analysis._interpolate_private import linear as regrid_linear
import iris.config as config
import iris.cube
import iris.exceptions
import iris.fileformats.um_cf_map
from iris.util import is_regular, regular_step

RuleResult = collections.namedtuple('RuleResult', ['cube', 'matching_rules', 'factories'])
Factory = collections.namedtuple('Factory', ['factory_class', 'args'])
ReferenceTarget = collections.namedtuple('ReferenceTarget',
                                         ('name', 'transform'))


class ConcreteReferenceTarget(object):
    """Everything you need to make a real Cube for a named reference."""

    def __init__(self, name, transform=None):
        #: The name used to connect references with referencees.
        self.name = name
        #: An optional transformation to apply to the cubes.
        self.transform = transform
        self._src_cubes = iris.cube.CubeList()
        self._final_cube = None

    def add_cube(self, cube):
        self._src_cubes.append(cube)

    def as_cube(self):
        if self._final_cube is None:
            src_cubes = self._src_cubes
            if len(src_cubes) > 1:
                # Merge the reference cubes to allow for
                # time-varying surface pressure in hybrid-presure.
                src_cubes = src_cubes.merge(unique=False)
                if len(src_cubes) > 1:
                    warnings.warn('Multiple reference cubes for {}'
                                  .format(self.name))
            src_cube = src_cubes[-1]

            if self.transform is None:
                self._final_cube = src_cube
            else:
                final_cube = src_cube.copy()
                attributes = self.transform(final_cube)
                for name, value in six.iteritems(attributes):
                    setattr(final_cube, name, value)
                self._final_cube = final_cube

        return self._final_cube


# Controls the deferred import of all the symbols from iris.coords.
# This "import all" is used as the rules file does not use fully qualified class names.
_rules_globals = None
_import_pending = True
def _rules_execution_environment():
    """
    Return an environment with the globals needed for rules code execution.

    This is needed as the rules file does not use fully qualified class names.
    If something is needed for rules execution, it can be added here.

    A master environment is built only when needed (the first call).
    This allows the import of various modules to be deferred, so we don't load
    all of those when we merely import this module.

    """
    global _import_pending, _rules_globals
    if _import_pending:
        # Get all module globals, and add other deferred imports.
        import iris.aux_factory
        import iris.coords
        import iris.coord_systems
        import iris.fileformats.um_cf_map
        # Take a copy of all this module's globals.
        _rules_globals = globals().copy()
        # Add various other stuff.
        # NOTE: these are equivalent to "from xx import *": not tidy !
        _rules_globals.update(iris.aux_factory.__dict__)
        _rules_globals.update(iris.coords.__dict__)
        _rules_globals.update(iris.coord_systems.__dict__)
        _rules_globals.update(iris.fileformats.um_cf_map.__dict__)
        _rules_globals.update(cf_units.__dict__)
        _import_pending = False

    return _rules_globals.copy()


# Dummy logging routine for when we don't want to do any logging.
def _dummy_log(format, filename, rules):
    pass


# Genuine logging routine
def _real_log(format, filename, rules):
    # Replace "\" with "\\", and "," with "\,"
    filename = filename.replace('\\', '\\\\').replace(',', '\\,')
    _rule_logger.info("%s,%s,%s" % (format, filename, ','.join([rule.id for rule in rules])))


# Debug logging routine (more informative that just object ids)
def _verbose_log(format, filename, rules):
    # Replace "\" with "\\", and "," with "\,"
    filename = filename.replace('\\', '\\\\').replace(',', '\\,')
    _rule_logger.info("\n\n-----\n\n%s,%s,%s" % (format, filename, '\n\n'.join([str(rule) for rule in rules])))


# Prepares a logger for file-based logging of rule usage
def _prepare_rule_logger(verbose=False, log_dir=None):
    # Default to the dummy logger that does nothing
    logger = _dummy_log

    # read the log_dir from the config file unless the log_dir argument is set
    if log_dir is None:
        log_dir = config.RULE_LOG_DIR
    # Only do real logging if we've been told the directory to use ...
    if log_dir is not None:
        user = getpass.getuser()

        # .. and if we haven't been told to ignore the current invocation.
        ignore = False
        ignore_users = config.RULE_LOG_IGNORE
        if ignore_users is not None:
            ignore_users = ignore_users.split(',')
            ignore = user in ignore_users

        if not ignore:
            try:
                hostname = platform.node() or 'UNKNOWN'
                log_path = os.path.join(log_dir, '_'.join([hostname, user]))
                file_handler = handlers.RotatingFileHandler(log_path, maxBytes=1e7, backupCount=5)
                format = '%%(asctime)s,%s,%%(message)s' % getpass.getuser()
                file_handler.setFormatter(logging.Formatter(format, '%Y-%m-%d %H:%M:%S'))

                global _rule_logger
                _rule_logger = logging.getLogger('iris.fileformats.rules')
                _rule_logger.setLevel(logging.INFO)
                _rule_logger.addHandler(file_handler)
                _rule_logger.propagate = False

                if verbose:
                    logger = _verbose_log
                else:
                    logger = _real_log

            except IOError:
                # If we can't create the log file for some reason then it's fine to just silently
                # ignore the error and fallback to using the dummy logging routine.
                pass

    return logger


# A flag to control all the text-rules and rules-logging deprecation warnings.
_enable_rules_deprecations = True

# A context manager to avoid the deprecation warnings for internal calls.
@contextmanager
def _disable_deprecation_warnings():
    global _enable_rules_deprecations
    old_flag_value = _enable_rules_deprecations
    try:
        _enable_rules_deprecations = False
        yield
    finally:
        _enable_rules_deprecations = old_flag_value


# Defines the "log" function for this module
# This is a 'private' version:  The public one is now deprecated (see on).
_log_rules = _prepare_rule_logger()


# Provide a public 'log' function, which issues a deprecation warning.
def log(*args, **kwargs):
    if _enable_rules_deprecations:
        warn_deprecated(
            "The `iris.fileformats.rules.log()` method is deprecated.")
    return _log_rules(*args, **kwargs)


class DebugString(str):
    """
    Used by the rules for debug purposes

    .. deprecated:: 1.10

    """
    def __init__(self, *args, **kwargs):
        warn_deprecated(
            "the `iris.fileformats.rules.DebugString class is deprecated.")
        super(DebugString, self).__init__(*args, **kwargs)


class CMAttribute(object):
    """
    Used by the rules for defining attributes on the Cube in a consistent manner.

    .. deprecated:: 1.10

    """
    __slots__ = ('name', 'value')
    def __init__(self, name, value):
        warn_deprecated(
            "the `iris.fileformats.rules.CmAttribute class is deprecated.")
        self.name = name
        self.value = value


class CMCustomAttribute(object):
    """
    Used by the rules for defining custom attributes on the Cube in a consistent manner.

    .. deprecated:: 1.10

    """
    __slots__ = ('name', 'value')
    def __init__(self, name, value):
        warn_deprecated(
            "the `iris.fileformats.rules.CmCustomAttribute class is "
            "deprecated.")
        self.name = name
        self.value = value


class CoordAndDims(object):
    """
    Used within rules to represent a mapping of coordinate to data dimensions.

    .. deprecated:: 1.10

    """
    def __init__(self, coord, dims=None):
        warn_deprecated(
            "the `iris.fileformats.rules.CoordAndDims class is deprecated.")
        self.coord = coord
        if dims is None:
            dims = []
        if not isinstance(dims, list):
            dims = [dims]
        self.dims = dims

    def add_coord(self, cube):
        added = False

        # Try to add to dim_coords?
        if isinstance(self.coord, iris.coords.DimCoord) and self.dims:
            if len(self.dims) > 1:
                raise Exception("Only 1 dim allowed for a DimCoord")

            # Does the cube already have a coord for this dim?
            already_taken = False
            for coord, coord_dim in cube._dim_coords_and_dims:
                if coord_dim == self.dims[0]:
                    already_taken = True
                    break

            if not already_taken:
                cube.add_dim_coord(self.coord, self.dims[0])
                added = True

        # If we didn't add it to dim_coords, add it to aux_coords.
        if not added:
            cube.add_aux_coord(self.coord, self.dims)

    def __repr__(self):
        return "<CoordAndDims: %r, %r>" % (self.coord.name, self.dims)


class Reference(iris.util._OrderedHashable):
    _names = ('name',)
    """
    A named placeholder for inter-field references.

    """


def calculate_forecast_period(time, forecast_reference_time):
    """
    Return the forecast period in hours derived from time and
    forecast_reference_time scalar coordinates.

    .. deprecated:: 1.10

    """
    warn_deprecated("the `iris.fileformats.rules.calculate_forecast_period "
                    "method is deprecated.")

    if time.points.size != 1:
        raise ValueError('Expected a time coordinate with a single '
                         'point. {!r} has {} points.'.format(time.name(),
                                                             time.points.size))

    if not time.has_bounds():
        raise ValueError('Expected a time coordinate with bounds.')

    if forecast_reference_time.points.size != 1:
        raise ValueError('Expected a forecast_reference_time coordinate '
                         'with a single point. {!r} has {} '
                         'points.'.format(forecast_reference_time.name(),
                                          forecast_reference_time.points.size))

    origin = time.units.origin.replace(time.units.origin.split()[0], 'hours')
    units = cf_units.Unit(origin, calendar=time.units.calendar)

    # Determine start and eof of period in hours since a common epoch.
    end = time.units.convert(time.bounds[0, 1], units)
    start = forecast_reference_time.units.convert(
        forecast_reference_time.points[0], units)
    forecast_period = end - start

    return forecast_period


class Rule(object):
    """
    A collection of condition expressions and their associated action expressions.

    Example rule::

        IF
            f.lbuser[6] == 2
            f.lbuser[3] == 101
        THEN
            CMAttribute('standard_name', 'sea_water_potential_temperature')
            CMAttribute('units', 'Celsius')

    .. deprecated:: 1.10

    """
    def __init__(self, conditions, actions):
        """Create instance methods from our conditions and actions."""
        if _enable_rules_deprecations:
            warn_deprecated(
                "the `iris.fileformats.rules.Rule class is deprecated.")
        if not hasattr(conditions, '__iter__'):
            raise TypeError('Variable conditions should be iterable, got: '+ type(conditions))
        if not hasattr(actions, '__iter__'):
            raise TypeError('Variable actions should be iterable, got: '+ type(actions))

        self._conditions = conditions
        self._actions = actions
        self._exec_actions = []

        self.id = str(hash((tuple(self._conditions), tuple(self._actions))))

        for i, condition in enumerate(conditions):
            self._conditions[i] = condition

        # Create the conditions method.
        self._create_conditions_method()

        # Create the action methods.
        for i, action in enumerate(self._actions):
            if not action:
                action = 'None'
            self._create_action_method(i, action)

    def _create_conditions_method(self):
        # Bundle all the conditions into one big string.
        conditions = '(%s)' % ') and ('.join(self._conditions)
        if not conditions:
            conditions = 'None'
        # Create a method to evaluate the conditions.
        # NB. This creates the name '_f' in the 'compile_locals' namespace,
        # which is then used below.
        code = 'def _f(self, field, f, pp, grib, cm): return %s' % conditions
        rules_globals = _rules_execution_environment()
        compile_locals = {}
        exec(compile(code, '<string>', 'exec'), rules_globals, compile_locals)
        # Make it a method of ours.
        _f = compile_locals['_f']
        self._exec_conditions = six.create_bound_method(_f, self)

    @abc.abstractmethod
    def _create_action_method(self, i, action):
        pass

    @abc.abstractmethod
    def _process_action_result(self, obj, cube):
        pass

    def __repr__(self):
        string = "IF\n"
        string += '\n'.join(self._conditions)
        string += "\nTHEN\n"
        string += '\n'.join(self._actions)
        return string

    def evaluates_true(self, cube, field):
        """Returns True if and only if all the conditions evaluate to True for the given field."""
        field = field
        f = field
        pp = field
        grib = field
        cm = cube

        try:
            result = self._exec_conditions(field, f, pp, grib, cm)
        except Exception as err:
            print('Condition failed to run conditions: %s : %s' % (self._conditions, err), file=sys.stderr)
            raise err

        return result

    def _matches_field(self, field):
        """Simple wrapper onto evaluates_true in the case where cube is None."""
        return self.evaluates_true(None, field)

    def run_actions(self, cube, field):
        """
        Adds to the given cube based on the return values of all the actions.

        """
        # Define the variables which the eval command should be able to see
        f = field
        pp = field
        grib = field
        cm = cube

        factories = []
        for i, action in enumerate(self._actions):
            try:
                # Run this action.
                obj = self._exec_actions[i](field, f, pp, grib, cm)
                # Process the return value (if any), e.g a CM object or None.
                action_factory = self._process_action_result(obj, cube)
                if action_factory:
                    factories.append(action_factory)

            except iris.exceptions.CoordinateNotFoundError as err:
                print('Failed (msg:%(error)s) to find coordinate, perhaps consider running last: %(command)s' % {'command':action, 'error': err}, file=sys.stderr)
            except AttributeError as err:
                print('Failed to get value (%(error)s) to execute: %(command)s' % {'command':action, 'error': err}, file=sys.stderr)
            except Exception as err:
                print('Failed (msg:%(error)s) to run:\n    %(command)s\nFrom the rule:\n%(me)r' % {'me':self, 'command':action, 'error': err}, file=sys.stderr)
                raise err

        return factories


class FunctionRule(Rule):
    """
    A Rule with values returned by its actions.

    .. deprecated:: 1.10

    """
    def _create_action_method(self, i, action):
        # CM loading style action. Returns an object, such as a coord.
        # Compile a new method for the operation.
        rules_globals = _rules_execution_environment()
        compile_locals = {}
        exec(
            compile(
                'def _f(self, field, f, pp, grib, cm): return %s' % (action, ),
                '<string>',
                'exec'),
            rules_globals, compile_locals)
        # Make it a method of ours.
        _f = compile_locals['_f']
        method = six.create_bound_method(_f, self)
        setattr(self, '_exec_action_%d' % (i, ), method)
        # Add to our list of actions.
        self._exec_actions.append(method)

    def _process_action_result(self, obj, cube):
        """Process the result of an action."""

        factory = None

        # NB. The names such as 'CoordAndDims' and 'CellMethod' are defined by
        # the "deferred import" performed by Rule.run_actions() above.
        if isinstance(obj, CoordAndDims):
            obj.add_coord(cube)

        #cell methods - not yet implemented
        elif isinstance(obj, CellMethod):
            cube.add_cell_method(obj)

        elif isinstance(obj, CMAttribute):
            # Temporary code to deal with invalid standard names from the translation table.
            # TODO: when name is "standard_name" force the value to be a real standard name
            if obj.name == 'standard_name' and obj.value is not None:
                cube.rename(obj.value)
            elif obj.name == 'units':
                # Graceful loading of units.
                try:
                    setattr(cube, obj.name, obj.value)
                except ValueError:
                    msg = 'Ignoring PP invalid units {!r}'.format(obj.value)
                    warnings.warn(msg)
                    cube.attributes['invalid_units'] = obj.value
                    cube.units = cf_units._UNKNOWN_UNIT_STRING
            else:
                setattr(cube, obj.name, obj.value)

        elif isinstance(obj, CMCustomAttribute):
            cube.attributes[obj.name] = obj.value

        elif isinstance(obj, Factory):
            factory = obj

        elif isinstance(obj, DebugString):
            print(obj)

        # The function returned nothing, like the pp save actions, "lbft = 3"
        elif obj is None:
            pass

        else:
            raise Exception("Object could not be added to cube. Unknown type: " + obj.__class__.__name__)

        return factory


class ProcedureRule(Rule):
    """
    A Rule with nothing returned by its actions.

    .. deprecated:: 1.10

    """
    def _create_action_method(self, i, action):
        # PP saving style action. No return value, e.g. "pp.lbft = 3".
        rules_globals = _rules_execution_environment()
        compile_locals = {}
        exec(compile('def _f(self, field, f, pp, grib, cm): %s' % (action, ),
                     '<string>',
                     'exec'),
             rules_globals, compile_locals)
        # Make it a method of ours.
        _f = compile_locals['_f']
        method = six.create_bound_method(_f, self)
        setattr(self, '_exec_action_%d' % (i, ), method)
        # Add to our list of actions.
        self._exec_actions.append(method)

    def _process_action_result(self, obj, cube):
        # This should always be None, as our rules won't create anything.
        pass

    def conditional_warning(self, condition, warning):
        pass  # without this pass statement it alsp print, "  Args:" on a new line.
        if condition:
            warnings.warn(warning)


class RulesContainer(object):
    """
    A collection of :class:`Rule` instances, with the ability to read rule
    definitions from files and run the rules against given fields.

    .. deprecated:: 1.10

    """
    def __init__(self, filepath=None, rule_type=FunctionRule):
        """Create a new rule set, optionally adding rules from the specified file.

        The rule_type defaults to :class:`FunctionRule`,
        e.g for CM loading actions that return objects, such as *AuxCoord(...)*

        rule_type can also be set to :class:`ProcedureRule`
        e.g for PP saving actions that do not return anything, such as *pp.lbuser[3] = 16203*
        """
        if _enable_rules_deprecations:
            warn_deprecated(
                "the `iris.fileformats.rules.RulesContainer class is deprecated.")
        self._rules = []
        self.rule_type = rule_type
        if filepath is not None:
            self.import_rules(filepath)

    def import_rules(self, filepath):
        """Extend the rule collection with the rules defined in the specified file."""
        # Define state constants
        IN_CONDITION = 1
        IN_ACTION = 2

        rule_file = os.path.expanduser(filepath)
        conditions = []
        actions = []
        state = None

        with open(rule_file, 'r') as file:
            for line in file:
                line = line.rstrip()
                if line == "IF":
                    if conditions and actions:
                        self._rules.append(self.rule_type(conditions, actions))
                    conditions = []
                    actions = []
                    state = IN_CONDITION
                elif line == "THEN":
                    state = IN_ACTION
                elif len(line) == 0:
                    pass
                elif line.strip().startswith('#'):
                    pass
                elif state == IN_CONDITION:
                    conditions.append(line)
                elif state == IN_ACTION:
                    actions.append(line)
                else:
                    raise Exception('Rule file not read correctly at line: ' +
                                    line)
        if conditions and actions:
            self._rules.append(self.rule_type(conditions, actions))

    def verify(self, cube, field):
        """
        Add to the given :class:`iris.cube.Cube` by running this set of
        rules with the given field.

        Args:

        * cube:
            An instance of :class:`iris.cube.Cube`.
        * field:
            A field object relevant to the rule set.

        Returns: (cube, matching_rules)

        * cube - the resultant cube
        * matching_rules - a list of rules which matched

        """
        matching_rules = []
        factories = []
        for rule in self._rules:
            if rule.evaluates_true(cube, field):
                matching_rules.append(rule)
                rule_factories = rule.run_actions(cube, field)
                if rule_factories:
                    factories.extend(rule_factories)
        return RuleResult(cube, matching_rules, factories)


def scalar_coord(cube, coord_name):
    """Try to find a single-valued coord with the given name."""
    found_coord = None
    for coord in cube.coords(coord_name):
        if coord.shape == (1,):
            found_coord = coord
            break
    return found_coord


def vector_coord(cube, coord_name):
    """Try to find a one-dimensional, multi-valued coord with the given name."""
    found_coord = None
    for coord in cube.coords(coord_name):
        if len(coord.shape) == 1 and coord.shape[0] > 1:
            found_coord = coord
            break
    return found_coord


def scalar_cell_method(cube, method, coord_name):
    """Try to find the given type of cell method over a single coord with the given name."""
    found_cell_method = None
    for cell_method in cube.cell_methods:
        if cell_method.method == method and len(cell_method.coord_names) == 1:
            name = cell_method.coord_names[0]
            if name == coord_name:
                coords = cube.coords(name)
                if len(coords) == 1:
                    found_cell_method = cell_method
    return found_cell_method


def has_aux_factory(cube, aux_factory_class):
    """
    Try to find an class:`~iris.aux_factory.AuxCoordFactory` instance of the
    specified type on the cube.

    """
    for factory in cube.aux_factories:
        if isinstance(factory, aux_factory_class):
            return True
    return False


def aux_factory(cube, aux_factory_class):
    """
    Return the class:`~iris.aux_factory.AuxCoordFactory` instance of the
    specified type from a cube.

    """
    aux_factories = [aux_factory for aux_factory in cube.aux_factories if
                     isinstance(aux_factory, aux_factory_class)]
    if not aux_factories:
        raise ValueError('Cube does not have an aux factory of '
                         'type {!r}.'.format(aux_factory_class))
    elif len(aux_factories) > 1:
        raise ValueError('Cube has more than one aux factory of '
                         'type {!r}.'.format(aux_factory_class))
    return aux_factories[0]


class _ReferenceError(Exception):
    """Signals an invalid/missing reference field."""
    pass


def _dereference_args(factory, reference_targets, regrid_cache, cube):
    """Converts all the arguments for a factory into concrete coordinates."""
    args = []
    for arg in factory.args:
        if isinstance(arg, Reference):
            if arg.name in reference_targets:
                src = reference_targets[arg.name].as_cube()
                # If necessary, regrid the reference cube to
                # match the grid of this cube.
                src = _ensure_aligned(regrid_cache, src, cube)
                if src is not None:
                    new_coord = iris.coords.AuxCoord(src.data,
                                                     src.standard_name,
                                                     src.long_name,
                                                     src.var_name,
                                                     src.units,
                                                     attributes=src.attributes)
                    dims = [cube.coord_dims(src_coord)[0]
                                for src_coord in src.dim_coords]
                    cube.add_aux_coord(new_coord, dims)
                    args.append(new_coord)
                else:
                    raise _ReferenceError('Unable to regrid reference for'
                                          ' {!r}'.format(arg.name))
            else:
                raise _ReferenceError("The source data contains no "
                                      "field(s) for {!r}.".format(arg.name))
        else:
            # If it wasn't a Reference, then arg is a dictionary
            # of keyword arguments for cube.coord(...).
            args.append(cube.coord(**arg))
    return args


def _regrid_to_target(src_cube, target_coords, target_cube):
    # Interpolate onto the target grid.
    sample_points = [(coord, coord.points) for coord in target_coords]
    result_cube = regrid_linear(src_cube, sample_points)

    # Any scalar coords on the target_cube will have become vector
    # coords on the resample src_cube (i.e. result_cube).
    # These unwanted vector coords need to be pushed back to scalars.
    index = [slice(None, None)] * result_cube.ndim
    for target_coord in target_coords:
        if not target_cube.coord_dims(target_coord):
            result_dim = result_cube.coord_dims(target_coord)[0]
            index[result_dim] = 0
    if not all(key == slice(None, None) for key in index):
        result_cube = result_cube[tuple(index)]
    return result_cube


def _ensure_aligned(regrid_cache, src_cube, target_cube):
    """
    Returns a version of `src_cube` suitable for use as an AuxCoord
    on `target_cube`, or None if no version can be made.

    """
    result_cube = None

    # Check that each of src_cube's dim_coords matches up with a single
    # coord on target_cube.
    try:
        target_coords = []
        for dim_coord in src_cube.dim_coords:
            target_coords.append(target_cube.coord(dim_coord))
    except iris.exceptions.CoordinateNotFoundError:
        # One of the src_cube's dim_coords didn't exist on the
        # target_cube... so we can't regrid (i.e. just return None).
        pass
    else:
        # So we can use `iris.analysis.interpolate.linear()` later,
        # ensure each target coord is either a scalar or maps to a
        # single, distinct dimension.
        target_dims = [target_cube.coord_dims(coord) for coord in target_coords]
        target_dims = list(filter(None, target_dims))
        unique_dims = set()
        for dims in target_dims:
            unique_dims.update(dims)
        compatible = len(target_dims) == len(unique_dims)

        if compatible:
            cache_key = id(src_cube)
            if cache_key not in regrid_cache:
                regrid_cache[cache_key] = ([src_cube.dim_coords], [src_cube])
            grids, cubes = regrid_cache[cache_key]
            # 'grids' is a list of tuples of coordinates, so convert
            # the 'target_coords' list into a tuple to be consistent.
            target_coords = tuple(target_coords)
            try:
                # Look for this set of target coordinates in the cache.
                i = grids.index(target_coords)
                result_cube = cubes[i]
            except ValueError:
                # Not already cached, so do the hard work of interpolating.
                result_cube = _regrid_to_target(src_cube, target_coords,
                                                target_cube)
                # Add it to the cache.
                grids.append(target_coords)
                cubes.append(result_cube)

    return result_cube


_loader_attrs = ('field_generator', 'field_generator_kwargs',
                 'converter', 'legacy_custom_rules')
class Loader(collections.namedtuple('Loader', _loader_attrs)):
    def __new__(cls, field_generator, field_generator_kwargs, converter,
                legacy_custom_rules=None):
        """
        Create a definition of a field-based Cube loader.

        Args:

        * field_generator
            A callable that accepts a filename as its first argument and
            returns an iterable of field objects.

        * field_generator_kwargs
            Additional arguments to be passed to the field_generator.

        * converter
            A callable that converts a field object into a Cube.

        Kwargs:

        * legacy_custom_rules
            An object with a callable `verify` attribute with two
            parameters: (cube, field). Legacy method for modifying
            Cubes during the load process. Default is None.

            .. deprecated:: 1.9

        """
        if legacy_custom_rules is not None:
            warn_deprecated('The `legacy_custom_rules` attribute is '
                            'deprecated.')
        return tuple.__new__(cls, (field_generator, field_generator_kwargs,
                                   converter, legacy_custom_rules))


ConversionMetadata = collections.namedtuple('ConversionMetadata',
                                            ('factories', 'references',
                                             'standard_name', 'long_name',
                                             'units', 'attributes',
                                             'cell_methods',
                                             'dim_coords_and_dims',
                                             'aux_coords_and_dims'))


def _make_cube(field, converter):
    # Convert the field to a Cube.
    metadata = converter(field)

    try:
        data = field._data
    except AttributeError:
        data = field.data

    cube = iris.cube.Cube(data,
                          attributes=metadata.attributes,
                          cell_methods=metadata.cell_methods,
                          dim_coords_and_dims=metadata.dim_coords_and_dims,
                          aux_coords_and_dims=metadata.aux_coords_and_dims)

    # Temporary code to deal with invalid standard names in the
    # translation table.
    if metadata.standard_name is not None:
        cube.rename(metadata.standard_name)
    if metadata.long_name is not None:
        cube.long_name = metadata.long_name
    if metadata.units is not None:
        # Temporary code to deal with invalid units in the translation
        # table.
        try:
            cube.units = metadata.units
        except ValueError:
            msg = 'Ignoring PP invalid units {!r}'.format(metadata.units)
            warnings.warn(msg)
            cube.attributes['invalid_units'] = metadata.units
            cube.units = cf_units._UNKNOWN_UNIT_STRING

    return cube, metadata.factories, metadata.references


def _resolve_factory_references(cube, factories, concrete_reference_targets,
                                regrid_cache={}):
    # Attach the factories for a cube, building them from references.
    # Note: the regrid_cache argument lets us share and reuse regridded data
    # across multiple result cubes.
    for factory in factories:
        try:
            args = _dereference_args(factory, concrete_reference_targets,
                                     regrid_cache, cube)
        except _ReferenceError as e:
            msg = 'Unable to create instance of {factory}. ' + str(e)
            factory_name = factory.factory_class.__name__
            warnings.warn(msg.format(factory=factory_name))
        else:
            aux_factory = factory.factory_class(*args)
            cube.add_aux_factory(aux_factory)


def _load_pairs_from_fields_and_filenames(fields_and_filenames, converter,
                                          user_callback_wrapper=None):
    # The underlying mechanism for the public 'load_pairs_from_fields' and
    # 'load_cubes'.
    # Slightly more complicated than 'load_pairs_from_fields', only because it
    # needs a filename associated with each field to support the load callback.
    concrete_reference_targets = {}
    results_needing_reference = []
    for field, filename in fields_and_filenames:
        # Convert the field to a Cube, passing down the 'converter' function.
        cube, factories, references = _make_cube(field, converter)

        # Post modify the new cube with a user-callback.
        # This is an ordinary Iris load callback, so it takes the filename.
        cube = iris.io.run_callback(user_callback_wrapper,
                                    cube, field, filename)
        # Callback mechanism may return None, which must not be yielded.
        if cube is None:
            continue

        # Cross referencing.
        for reference in references:
            name = reference.name
            # Register this cube as a source cube for the named reference.
            target = concrete_reference_targets.get(name)
            if target is None:
                target = ConcreteReferenceTarget(name, reference.transform)
                concrete_reference_targets[name] = target
            target.add_cube(cube)

        if factories:
            results_needing_reference.append((cube, factories, field))
        else:
            yield (cube, field)

    regrid_cache = {}
    for (cube, factories, field) in results_needing_reference:
        _resolve_factory_references(
            cube, factories, concrete_reference_targets, regrid_cache)
        yield (cube, field)


def load_pairs_from_fields(fields, converter):
    """
    Convert an iterable of fields into an iterable of Cubes using the
    provided convertor.

    Args:

    * fields:
        An iterable of fields.

    * convertor:
        An Iris convertor function, suitable for use with the supplied fields.
        See the description in :class:`iris.fileformats.rules.Loader`.

    Returns:
        An iterable of (:class:`iris.cube.Cube`, field) pairs.

    """
    return _load_pairs_from_fields_and_filenames(
        ((field, None) for field in fields),
        converter)


def load_cubes(filenames, user_callback, loader, filter_function=None):
    if isinstance(filenames, six.string_types):
        filenames = [filenames]

    def _generate_all_fields_and_filenames():
        for filename in filenames:
            for field in loader.field_generator(
                    filename, **loader.field_generator_kwargs):
                # evaluate field against format specific desired attributes
                # load if no format specific desired attributes are violated
                if filter_function is None or filter_function(field):
                    yield (field, filename)

    def loadcubes_user_callback_wrapper(cube, field, filename):
        # First run any custom user-provided rules.
        if loader.legacy_custom_rules:
            warn_deprecated('The `legacy_custom_rules` attribute of '
                            'the `loader` is deprecated.')
            loader.legacy_custom_rules.verify(cube, field)

        # Then also run user-provided original callback function.
        result = cube
        if user_callback is not None:
            result = user_callback(cube, field, filename)
        return result

    all_fields_and_filenames = _generate_all_fields_and_filenames()
    for cube, field in _load_pairs_from_fields_and_filenames(
            all_fields_and_filenames,
            converter=loader.converter,
            user_callback_wrapper=loadcubes_user_callback_wrapper):
        yield cube
