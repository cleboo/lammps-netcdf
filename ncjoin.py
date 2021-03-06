#! /usr/bin/env python

# ======================================================================
# LAMMPS NetCDF dump style
# https://github.com/pastewka/lammps-netcdf
# Lars Pastewka, lars.pastewka@kit.edu
#
# Copyright (2011-2013) Fraunhofer IWM
# Copyright (2014) Karlsruhe Institute of Technology
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your argument) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
# ======================================================================

"""
Join a individual NetCDF trajectory files into a single one.
"""

import os
import sys
from argparse import ArgumentParser

import numpy as np

from netCDF4 import Dataset

###

FRAME_DIM = 'frame'
ATOM_DIM = 'atom'

###

def get_nearest_indices(time, every):
    """
    Given a list of times, return indices that are most closely to evenly
    spaced time intervals of length *every*.
    """

    time = np.asarray(time)
    r = [ ]
    n = int(np.min(time)/every)
    m = int(np.max(time)/every)+1
    last_j = -1
    for i in range(n, m):
        difftime = np.abs(time-i*every)
        j = np.argmin(difftime)
        if difftime[j] < 1.0 and j != last_j:
            r += [ j ]
            last_j = j
    return np.array(r)

###

def strip_fn(fn):
    if len(fn) > 0 and fn[0] == '+':
        return fn[1:]
    return fn

###

def fix_time(time):
    if len(time) > 2 and abs(time[2]-time[1]-(time[1]-time[0])) > 1e-3:
        time = np.array(time)
        time[0] = time[1]-(time[2]-time[1])
    return time


def open_trajs(trajfns, time_var='time', test_var='coordinates', test_tol=1e-6):
    """
    Open multiple NetCDF trajectory files and check that they are in order.
    Remove overlap if files overlap. Returns list of tuples. Tuple contains
        filename, netCDF4 Dataset object, first frame, last frame
    """

    test_index = None
    i = test_var.find('[')
    j = test_var.find(']')
    if i > 0 and j > 0 and i < j:
        test_index = int(test_var[i+1:j])
        test_var = test_var[:i]

    test_tol = np.asarray(test_tol)

    data_f = zip(trajfns, map(Dataset, map(strip_fn, trajfns)))
    filtered_data_f = [ ]

    fn2, data2 = data_f[0]
    last_time = None
    first1 = 0
    for i in range(len(data_f)-1):
        fn1, data1 = data_f[i]
        fn2, data2 = data_f[i+1]

        print '... %s and %s ...' % ( fn1, fn2 )

        max_maxdiff = np.zeros_like(test_tol)
        min_maxdiff = test_tol+1e12

        if fn2[0] == '+':
            # Skip test and use all frames, including last
            first2 = 0
            last1 = data1.variables[test_var].shape[0]
        else:
            test1 = data1.variables[test_var]
            test2 = data2.variables[test_var]
            if test_var == time_var:
                test1 = fix_time(test1)
                test2 = fix_time(test2)
            if test_index is not None:
                test1 = test1[:, test_index]
                test2 = test2[:, test_index]

            maxdiff = test_tol+1.0
            first2 = -1
            while first2 < min(test2.shape[0]-1, 5) and \
                      np.any(maxdiff > test_tol):
                first2 += 1
                # Last element in previous file
                last1 = test1.shape[0]-1
                # Maximum difference in test variable
                maxdiff = np.abs(test1[last1] - test2[first2])
                if test_tol.shape == ():
                    maxdiff = np.max(maxdiff)
                while last1 >= 0 and np.any(maxdiff > test_tol):
                    #print 'Frame %i of %s does not agree with frame %i of %s ' \
                    #      '(maximum difference %e). Checking frame %i.' % \
                    #      ( last1, fn1, first2, fn2, maxdiff, last1-1 )
                    max_maxdiff = np.maximum(maxdiff, max_maxdiff)
                    min_maxdiff = np.minimum(maxdiff, min_maxdiff)
                    last1 -= 1
                    maxdiff = np.max(np.abs(test1[last1] - test2[first2]))
                    if test_tol.shape == ():
                        maxdiff = np.max(maxdiff)
                max_maxdiff = np.maximum(maxdiff, max_maxdiff)
                min_maxdiff = np.minimum(maxdiff, min_maxdiff)

        # Sanity check. Frame *last1* of previous file should be identical to
        # frame 0 of current file.
        if last1 < 0:
            raise RuntimeError('{} and {} are not consecutive. Minimum '
                               'residual found was {}, maximum residual {}. '
                               'It may help to increase *test_tol*.' \
                               .format(fn1, fn2, min_maxdiff, max_maxdiff))

        # Retrieve time information. If file has no time information number
        # the individual frames consecutively.
        if time_var in data1.variables:
            time1 = data1.variables[time_var]
        else:
            time1 = np.arange(data1.variables[test_var].shape[0])
        data_slice = slice(first1, last1)
        time = time1[data_slice]
        # Some files have a bug where the first time slot is zero. Fix by
        # assuming constant time offset between frames.
        time = fix_time(time)

        if last_time is not None:
            # These files are consecutive in the test_var, but may not be
            # consecutive in time. Add an offset to the time.
            time += last_time - time[0]
        filtered_data_f += [ ( fn1, data1, data_slice, time ) ]

        # This becomes the last time of the previous file when in the loop
        if last1 >= len(time1):
            last_time = time[-1]+(time[-2]-time1[-1])*(len(time1)-last1+1)
        else:
            last_time = time[-1]

        # Start next file where we think it should start
        first1 = first2

    if time_var in data2.variables:
        time = data2.variables[time_var][:]
    else:
        time = np.arange(data2.variables[test_var].shape[0])
    # Some files have a bug where the first time slot is zero. Fix by
    # assuming constant time offset between frames.
    if len(time) > 2 and abs(time[2]-time[1]-(time[1]-time[0])) > 1e-3:
        time[0] = time[1]-(time[2]-time[1])

    if last_time is not None:
        # These files are consecutive in the test_var, but may not be
        # consecutive in time. Add an offset to the time.
        time += last_time - time[0]
    filtered_data_f += [ ( fn2, data2, slice(first1, len(time)), time ) ]

    return filtered_data_f

###

def filter_trajs(idata_f, every):
    # Create a list of all frames
    idata_oframe = reduce(lambda a,b: a+b,
                          [ [ ( fn, data, i, time[i] )
                              for i in range(len(time))[data_slice] ]
                            for fn, data, data_slice, time in idata_f ],
                          [])

    # Get indices that corresponds to roughly equally spaced time slots
    i = get_nearest_indices([time for fn, data, i, time in idata_oframe], every)
    if len(i) == 0:
        raise RuntimeError('No frames left after filtering.')
    else:
        idata_oframe = [ idata_oframe[_i] for _i in i ]

    # Consolidate into a list that contains per-file information
    filtered_idata_f = [ ]
    cur_fn, cur_data, cur_slice, cur_time = idata_oframe[0]
    cur_slice = [ ]
    cur_time = [ ]
    for fn, data, i, time in idata_oframe:
        if data is not cur_data:
            filtered_idata_f += [ ( cur_fn, cur_data, np.array(cur_slice),
                                    np.array(cur_time) ) ]
            cur_fn = fn
            cur_data = data
            cur_slice = [ ]
            cur_time = [ ]
        cur_slice += [ i ]
        cur_time += [ time ]
    filtered_idata_f += [ ( cur_fn, cur_data, np.array(cur_slice),
                            np.array(cur_time) ) ]
    return filtered_idata_f


### Parse command line arguments

parser = ArgumentParser(description='Join multiple NetCDF trajectory files '
                                    'into a single one. The code uses some '
                                    'heuristics to determine if files are '
                                    'consecutive.')
parser.add_argument('filenames', metavar='FN', nargs='+',
                    help='file to concatenate')
parser.add_argument('-e', '--every', dest='every', type=float,
                    help='copy only frames at times that are multiples of '
                         'EVERY',
                    metavar='EVERY')
parser.add_argument('-v', '--test_var', dest='test_var', default='coordinates',
                    help="use variable VAR to test if two frames are "
                         "identical (default: 'coordinates')",
                    metavar='VAR')
parser.add_argument('-t', '--test_tol', dest='test_tol',
                    default='1e-6',
                    help='use tolerance TOL to test if two frames are '
                         'identical',
                    metavar='TOL')
parser.add_argument('-k', '--netcdf_format', dest='netcdf_format',
                    default='NETCDF3_64BIT',
                    help="use NetCDF format KIND; available formats are "
                         "'NETCDF3_CLASSIC', 'NETCDF3_64BIT' (default), "
                         "'NETCDF4_CLASSIC' and 'NETCDF4'",
                    metavar='KIND')
parser.add_argument('-x', '--exclude', dest='exclude',
                    help='exclude variables EXCLUDE (comman separated list) '
                         'from being written to the output file',
                    metavar='EXCLUDE')
parser.add_argument('-i', '--index', dest='index', default='id',
                    help="variable INDEX contains particle ids (default: "
                         "INDEX='id')",
                    metavar='INDEX')
parser.add_argument('-o', '--index-offset', dest='index_offset', type=int,
                    default=-1,
                    help='OFFSET will be added to particle id to get zero-based'
                         ' particle index (default: OFFSET=-1)',
                    metavar='OFFSET')
arguments = parser.parse_args()
if ',' in arguments.test_tol:
    arguments.test_tol = np.array([float(x) for x in arguments.test_tol.split(',')])
else:
    arguments.test_tol = float(arguments.test_tol)
print 'every =', arguments.every, ', test_var =', arguments.test_var, \
      ', test_tol =', arguments.test_tol, ', exclude =', arguments.exclude, \
      ', index =', arguments.index, ', index_offset =', arguments.index_offset


### Sanity check

if os.path.exists('traj.nc'):
    raise RuntimeError('traj.nc exists already.')


### Open input files and filter if requested

print 'Opening files and checking file order...'
idata_f = open_trajs(arguments.filenames, test_var=arguments.test_var,
                     test_tol=arguments.test_tol)
if arguments.every is not None:
    idata_f = filter_trajs(idata_f, arguments.every)


# Create output file
odata = Dataset('traj.nc', 'w', clobber=False, format=arguments.netcdf_format)


### Copy global attributes

for attr_str in idata_f[0][1].ncattrs():
    print "> creating global attribute '%s'..." % attr_str
    odata.setncattr(attr_str, idata_f[0][1].getncattr(attr_str))


### Prepare exclude list

exclude_list = set([arguments.index])
if arguments.exclude is not None:
    exclude_list = exclude_list.union(set(arguments.exclude.split(',')))


### Copy everything else

cursor = 0
last_data = None
for trajfn, idata, data_slice, time in idata_f:
    print "Appending '%s' starting at frame %i..." % ( trajfn, cursor )
    print 'File contains %i relevant time slots: ' % len(time), time

    index = None
    if arguments.index in idata.variables:
        index = idata.variables[arguments.index]
        if len(index.dimensions) != 2 or index.dimensions[0] != FRAME_DIM or \
            index.dimensions[1] != ATOM_DIM:
            raise RuntimeError('*INDEX* variable must have dimensions (frame, '
                               'atom).')

    for var_str, var in idata.variables.iteritems():
        if var_str in exclude_list:
            continue

        if var_str not in odata.variables:
            if arguments.netcdf_format == 'NETCDF4' and var_str in idata.dimensions:
                # In NETCDF4 (HDF5) there cannot be dimension and variable of
                # the same name
                print "= skipping variable '%s' because there is a dimension " \
                      "of the same name" % var_str
            else:
                print "> creating variable '%s'..." % var_str
                for dim_str in var.dimensions:
                    if dim_str not in odata.dimensions:
                        print "> creating dimension '%s'......" % dim_str
                        dim = idata.dimensions[dim_str]
                        if dim.isunlimited():
                            odata.createDimension(dim_str)
                        else:
                            odata.createDimension(dim_str, len(dim))
                odata.createVariable(var_str, var.dtype, var.dimensions)
                ovar = odata.variables[var_str]
                for attr_str in var.ncattrs():
                    print "> creating attribute '%s' of variable '%s'..." % \
                          ( attr_str, var_str )
                    ovar.setncattr(attr_str, var.getncattr(attr_str))

    for var_str, var in idata.variables.iteritems():
        if var_str in exclude_list:
            continue

        if var_str not in idata.dimensions:
            if var.dimensions[0] == FRAME_DIM:
                print "Copying variable '%s'..." % var_str
                if var_str == 'time':
                    odata.variables[var_str][cursor:] = time
                else:
                    n = var.shape[0]
                    for oframe, iframe in enumerate(np.arange(n)[data_slice]):
                        sys.stdout.write('=== {0}/{1} -> {2} ===\r' \
                            .format(iframe+1, n, cursor+oframe+1))
                        var_data = np.array(var[iframe])
                        if not np.isfinite(var_data).all():
                            print "Data is nan or inf in variable '{}' at " \
                                  "frame {}.".format(var_str, cursor)
                        # Reorder atoms by index if exists
                        if index is not None and len(var.dimensions) > 1 and \
                            var.dimensions[1] == ATOM_DIM:
                            sorted_var_data = np.zeros_like(var_data)
                            sorted_var_data[index[iframe] + \
                                            arguments.index_offset] = var_data
                            var_data = sorted_var_data
                        odata.variables[var_str][cursor+oframe] = var_data
            else:
                if not last_data or var_str not in last_data.variables:
                    print "Copying variable '%s'..." % var_str
                    odata.variables[var_str][:] = var[:]
                else:
                    print "Checking variable '%s' for consistency across files..."%\
                          var_str
                    if np.any(last_data.variables[var_str][:] != var[:]):
                        raise RuntimeError("Data for per-file variable '%s' "
                                           "differs in '%s' and '%s'." % 
                                           ( var_str, trajfns[i-1], trajfns[i] ))

    cursor += len(time)
    last_time = time[-1]
    if last_data:
        last_data.close()
    last_data = idata
last_data.close()
odata.close()
print 'Successfully wrote {0} frames.'.format(cursor)
