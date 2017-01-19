# run this file by using command:
#$ mpirun -np 4 python FillingScheme_and_Feedback_Test.py


from __future__ import division

import sys, os
BIN = os.path.expanduser("../../")
sys.path.append(BIN)

import time
import numpy as np
import seaborn as sns
from mpi4py import MPI
import matplotlib.pyplot as plt
from scipy.constants import c, e, m_p, pi

from PyHEADTAIL.particles.slicing import UniformBinSlicer
from PyHEADTAIL_feedback.feedback import OneboxFeedback
from PyHEADTAIL_feedback.processors.multiplication import ChargeWeighter
from PyHEADTAIL_feedback.processors.misc import Bypass


def pick_signals(processor, source = 'input'):

    if source == 'input':
        bin_edges = processor.input_signal_parameters.bin_edges
        raw_signal = processor.input_signal
    elif source == 'output':
        bin_edges = processor.output_signal_parameters.bin_edges
        raw_signal = processor.output_signal
    else:
        raise ValueError('Unknown value for the data source')

    print 'len(bin_edges): ' + str(len(bin_edges))
    print 'len(raw_signal): ' + str(len(raw_signal))

    t = np.zeros(len(raw_signal)*4)
    z = np.zeros(len(raw_signal)*4)
    bins = np.zeros(len(raw_signal)*4)
    signal = np.zeros(len(raw_signal)*4)
    value = 1.


    for i, edges in enumerate(bin_edges):
        z[4*i] = edges[0]
        z[4*i+1] = edges[0]
        z[4*i+2] = edges[1]
        z[4*i+3] = edges[1]
        bins[4*i] = 0.
        bins[4*i+1] = value
        bins[4*i+2] = value
        bins[4*i+3] = 0.
        signal[4*i] = 0.
        signal[4*i+1] = raw_signal[i]
        signal[4*i+2] = raw_signal[i]
        signal[4*i+3] = 0.
        value *= -1

    t = z/c

    return (t, z, bins, signal)


def kicker(bunch):
    bunch.x *= 0
    bunch.xp *= 0
    bunch.y *= 0
    bunch.yp *= 0
    bunch.x[:] += 2e-2 * np.sin(2.*pi*np.mean(bunch.z)/1000.)

plt.switch_backend('TkAgg')
sns.set_context('talk', font_scale=1.3)
sns.set_style('darkgrid', {
    'axes.edgecolor': 'black',
    'axes.linewidth': 2,
    'lines.markeredgewidth': 1})


comm = MPI.COMM_WORLD
size = comm.Get_size()
rank = comm.Get_rank()

n_turns = 100
chroma = 0

n_segments = 1
n_bunches = 13
filling_scheme = [401 + 20*i for i in range(n_bunches)]
n_macroparticles = 40000
intensity = 2.3e11


# BEAM AND MACHNINE PARAMETERS
# ============================
from test_tools import MultibunchMachine
machine = MultibunchMachine(n_segments=n_segments)

epsn_x = 2.e-6
epsn_y = 2.e-6
sigma_z = 0.081

bunches = machine.generate_6D_Gaussian_bunch_matched(
    n_macroparticles, intensity, epsn_x, epsn_y, sigma_z=sigma_z,
    filling_scheme=filling_scheme, kicker=kicker)

# CREATE BEAM SLICERS
# ===================
slicer = UniformBinSlicer(50, n_sigma_z=3)

processors_x = [
    Bypass(store_signal = True),
    ChargeWeighter(normalization = 'average',store_signal  = True),
]
processors_y = [
    Bypass(store_signal = True),
    ChargeWeighter(normalization = 'average',store_signal  = True),
]

gain = 0.1

feedback_map = OneboxFeedback(gain, slicer, processors_x, processors_y, axis='displacement', mpi = True)


# TRACKING LOOP
# =============
machine.one_turn_map.append(feedback_map)
# machine.one_turn_map.append(wake_field)

s_cnt = 0
monitorswitch = False
if rank == 0:
    print '\n--> Begin tracking...\n'

print 'Tracking'
for i in range(n_turns):

    if rank == 0:
        t0 = time.clock()
    machine.track(bunches)

    if rank == 0:
        t1 = time.clock()
        print('Turn {:d}, {:g} ms, {:s}'.format(i, (t1-t0)*1e3, time.strftime(
            "%d/%m/%Y %H:%M:%S", time.localtime())))

if rank == 0:
    fig, (ax1, ax2) = plt.subplots(2, figsize=(14, 14), sharex=False)

    for i, processor in enumerate(processors_x):
        print 'Processor: ' + str(i)
        t, z, bins, signal = pick_signals(processor,'output')
        ax1.plot(z, bins, label =  processor.label)
        ax2.plot(z, signal, label =  processor.label)
        if i == 0:
            print t
            print z
            print bins
            print signal

    # ax3.plot(processors_x[0]._CDF_time,processors_x[0]._PDF,'r-')
    ax1.set_xlabel('Z position [m]')
    ax1.set_ylabel('Bins')


    ax2.set_xlabel('Z position [m]')
    ax2.set_ylabel('Signal after the processor')


    plt.legend()
    plt.show()
