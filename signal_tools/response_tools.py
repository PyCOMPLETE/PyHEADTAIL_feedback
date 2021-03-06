import math
import numpy as np
from scipy.constants import c, pi
from scipy import interpolate
from signal_generators import sine_wave
from signal_generators import binary_impulse, sine_impulse, triangle_impulse, square_impulse
import copy
from signal_generators import CircularPointBeam

from ..core import process

# TODO:
#   * add analytical formula for excitation
#   * multi plane for Signal handling
#   * add extract signals
#   * rewrite signal class to be based on the general abstract classes

""" This file contains tools for testing signal processors, calculating signal responses for different processor chains
    and studying the control theory behind the damping.
"""


def track_signal(n_turns, signal, processors, plane = 'x'):

    """ simulates bunch in the PyHEADTAIL, i.e.


    :param n_turns: a number of turns will be tracked
    :param signal: a signal object
    :param processors: a list of processors, 'feedback'
    :param plane: the plane where rotation occurs
    :return:
    """
    for i in xrange(n_turns):
        signal.pick_signal(plane)
        signal.pass_signal(processors)
        signal.make_correction(plane)
        signal.rotate(plane)


def signal_response(signal,processors,plane = 'x'):
    """ Calculates a response of the input signal from the given processors

    :param signal:      an input signal
    :param processors:  a list of signal processors
    :param plane:       a plane (x, y or z) where the response is calculated
    :return: (t, z, impulse, response), which are numpy arrays:
            t:          time
            z:          position
            impulse:    input signal
            response:   output signal
    """

    processors_for_use = copy.deepcopy(processors)

    t = signal.t
    z = signal.z
    input_parameters, input_signal = signal.signal()

    output_parameters, output_signal = process(input_parameters, input_signal, processors_for_use)

    return t, z, input_signal, output_signal

def frequency_response(processors, time_scale, resp_symmetry='symmetric', f_range = None, n_f_points = 32, n_min_periods = 32, n_min_per_period = 64):

    """ Calculates a frequency response for the given processors.

    :param processors:      a list of signal processors
    :param time_scale:      a characteristic time scale of the processors (e.g. determined by cut-off frequencies of filters)
    :param resp_symmetry:   a symmetry of the impulse reponses of the processors.
    :param f_range:         a frequency range where the response is calculated
    :param n_f_points:      a number of frequencies included to the frequency range (by using logspace)
    :param n_min_periods:   a minimum number of periods included to calculation
    :param n_min_per_period: a minimum number of data points in one period
    :return: (frequencies, amplitudes, phase_shifts), which are numpy arrays
    """

    def calculate_parameters(t_period,t,signal,ref_signal):

        """ Determines the amplitude and the phase shift for the signal. Phase shift is determined by calculating
            cross correlation between a time-shifted signal and the reference signal. The time shift, which gives
            the highest correlation correspond to phase(/time) shift between the signal and the reference signal

        :param t_period: time of the period in the reference signal
        :param t: time points for signals
        :param signal: signal
        :param ref_signal: reference signal
        :return: amplitude, phase_shift
        """

        phase_steps = np.linspace(-100,100,2001)
        values = []

        ref_data_points = None

        if resp_symmetry == 'symmetric':
            start_period = np.floor((np.amax(t) - np.amin(t))/(2.*t_period))
            ref_data_points = (t >= ((start_period - 1.)* t_period))*(t < ((start_period + 1.)* t_period))
        elif resp_symmetry == 'delayed':
            ref_data_points = (t >= (np.amax(t) - 3.* t_period))*(t < (np.amax(t) - 1.* t_period))
        elif resp_symmetry == 'advanced':
            ref_data_points = (t >= (np.amin(t) + 1.* t_period))*(t < (np.amin(t) + 3.* t_period))

        ref_data_time = t[ref_data_points]
        ref_data = ref_signal[ref_data_points]
        amplitude_data = signal[ref_data_points]
        for phase in phase_steps:
            tck = interpolate.splrep(t + phase * t_period / 360., signal, s=0)
            cor_data = interpolate.splev(ref_data_time, tck, der=0)
            values.append(np.sum(ref_data*cor_data))

        values = np.array(values)
        phase_shift_point = values == np.max(values)
        phase_shift = phase_steps[phase_shift_point]
        phase_shift = phase_shift[0]
        amplitude = np.amax(np.abs(amplitude_data))

        return amplitude, phase_shift

    if f_range is None:
        frequencies = np.logspace(np.log10(0.01 / time_scale), np.log10(100. / time_scale), n_f_points)
    else:
        frequencies = np.logspace(np.log10(f_range[0]),np.log10(f_range[1]),n_f_points)

    amplitudes = []
    phase_shifts = []

    for f in frequencies:
        n_periods = max(n_min_periods, int(math.ceil(1.*time_scale*f)))
        n_per_period = max(n_min_per_period,4./(time_scale*f))

        processors_for_use = copy.deepcopy(processors)
        signal = sine_wave(f,1.,n_periods,n_per_period)

        timed = signal.t
        ref_parameters, ref_signal = signal.signal()
#        print len(timed)
        input_parameters, input_signal = signal.signal()
#        print input_parameters
        response_parameters, response_signal = process(input_parameters, input_signal, processors_for_use)

        amplitude, phase_shift = calculate_parameters(1./f,timed,response_signal,ref_signal)

        amplitudes.append(amplitude)
        phase_shifts.append(phase_shift)
#        print 'f={:.2e} -> {:.2e}, {:.2f} deg'.format(f,amplitude,phase_shift)

    return frequencies, np.array(amplitudes), np.array(phase_shifts)


def impulse_response(processors, time_range, n_points=501, impulse_type = 'binary', impulse_length = None):

    """ Calculates an impulse response for the given signal processors

    :param processors: a list of signal processors
    :param time_range: time range, where the impulse response is calculated (array or tuple)
    :param n_points: total number of points in the signal
    :param impulse_type: available options are:
            'binary': impulse consists of only one non-zero value (default)
            'square': half period of sine signal (i.e. a box signal)
            'sine': half period of sine signal (positive part)
            'triangle' half period  of triangle signal (positive part)
            'bipolar_square': one period of square signal
            'bipolar_sine': one period of sine signal
            'bipolar_triangle' one period of triangle signal
    :param impulse_length: if the type of the impulse is not binary, this parameter sets the length of the impulse. If
            empty, the impulse length is 1/10 of the time range
    :return: (t, z, impulse, response), which are numpy arrays:
            t:          time
            z:          position
            impulse:    input signal
            response:   output signal
    """

    amplitude = 1.
    signal = None

    if impulse_length is None:
        impulse_length = ((time_range[1] - time_range[0]) / 10.)

    def calculate_parameters(type):
        f = n_periods = None

        if type == 'unipolar':
            f = 0.5 / impulse_length
            n_periods = 0.5
        elif type == 'bipolar':
            f = 1. / impulse_length
            n_periods = 1.0

        total_periods = ((time_range[1] - time_range[0]) * f)
        n_per_period = int(n_points / total_periods)
        n_zero_periods = (total_periods - n_periods) / 2.

        return f, amplitude, n_periods, n_per_period, n_zero_periods

    if impulse_type == 'binary':
        signal = binary_impulse(time_range, n_points, amplitude)
    elif impulse_type == 'square':
        duty_cycle = 1.
        f, amplitude, n_periods, n_per_period, n_zero_periods = calculate_parameters('unipolar')
        signal = square_impulse(f, amplitude, duty_cycle, n_periods, n_per_period, n_zero_periods)
    elif impulse_type == 'sine':
        f, amplitude, n_periods, n_per_period, n_zero_periods = calculate_parameters('unipolar')
        signal = sine_impulse(f, amplitude, n_periods, n_per_period, n_zero_periods)
    elif impulse_type == 'triangle':
        f, amplitude, n_periods, n_per_period, n_zero_periods = calculate_parameters('unipolar')
        signal = triangle_impulse(f, amplitude, n_periods, n_per_period, n_zero_periods)
    elif impulse_type == 'bipolar_square':
        duty_cycle = 1.
        f, amplitude, n_periods, n_per_period, n_zero_periods = calculate_parameters('bipolar')
        signal = square_impulse(f, amplitude, duty_cycle, n_periods, n_per_period, n_zero_periods)
    elif impulse_type == 'bipolar_sine':
        f, amplitude, n_periods, n_per_period, n_zero_periods = calculate_parameters('bipolar')
        signal = sine_impulse(f, amplitude, n_periods, n_per_period, n_zero_periods)
    elif impulse_type == 'bipolar_triangle':
        f, amplitude, n_periods, n_per_period, n_zero_periods = calculate_parameters('bipolar')
        signal = triangle_impulse(f, amplitude, n_periods, n_per_period, n_zero_periods)

    processors_to_use = copy.deepcopy(processors)

    t = signal.t
    z = signal.z
    parameters, impulse = signal.signal()
    input_parameters, input_signal = signal.signal()
#        print input_parameters
    response_parameters, response = process(input_parameters, input_signal, processors_to_use)

    return t, z, impulse, response



class DamperImpulseResponse(object):
    """ A tracer which damps beam oscillations as a trasverse damper.
    """
    def __init__(self, processors, circumference, h_bunch, beta_beam, impulse_length, wait_before=10):
        """
        Parameters
        ----------
        processors : list
            A list of signal processors
        circumference : float
            Accelerator circumference in meters
        h_bunch: int 
            harmonic bunch or sampling number of the accelerator    
        beta_beam: float
            relativistic beta of the beam
        impulse_length : int
            Maximum length of the impulse response in turns
        wait_before : int
            Number of turns waited before the impulse is sent to system. This is
            required by some signal processors, which do not return signal before
            their internal buffer is filled
        """
        
        self.processors = processors
        self.circumference = circumference
        self.h_bunch = h_bunch
        self.beta_beam = beta_beam
        self.impulse_length = impulse_length
        self.wait_before = wait_before
        
        
        # this tools uses a point like beam object as a signal generator
        filling_scheme = np.arange(self.h_bunch)
        self.beam = CircularPointBeam(filling_scheme, circumference, self.h_bunch, 1.,
                             circular_overlapping=0, n_segments = 1, beta_x = 1.)
        
        self.impulse_bin = int(self.h_bunch/2)
        self.beam.x[self.impulse_bin] =+ 1.



    def get_impulse_response(self, **kwargs):

        # generates signal from the beam
        parameters, signal = self.beam.signal('x')
        empty_signal = np.zeros(len(signal))


        turn_by_turn_impulses = []
            


        for i in range(self.impulse_length+self.wait_before):
            
            if i == self.wait_before:
                # processes the signal
                kick_parameters_x, kick_signal_x = process(parameters, signal, self.processors,
                                                           slice_sets=self.beam.slice_sets, **kwargs)
            else:
                # processes the signal
                kick_parameters_x, kick_signal_x = process(parameters, empty_signal, self.processors,
                                                           slice_sets=self.beam.slice_sets, **kwargs)
            if i >= self.wait_before:    
                turn_by_turn_impulses.append(np.copy(kick_signal_x))
        
        sampling_rate_multiplication = int(len(turn_by_turn_impulses[-1])/len(empty_signal))
        
        parsed_turns = []
        for i, d in enumerate(turn_by_turn_impulses):
            if i == 0:
                parsed_turns.append(d[self.impulse_bin*sampling_rate_multiplication:])
            elif i == len(turn_by_turn_impulses)-1:
                parsed_turns.append(d[:self.impulse_bin*sampling_rate_multiplication])
            else:
                parsed_turns.append(d)
    
        parsed_impulse_response = np.concatenate(parsed_turns)
        samples = np.linspace(0,len(parsed_impulse_response)/float(sampling_rate_multiplication),len(parsed_impulse_response))
        turns = samples/float(self.h_bunch)
        time = samples*self.circumference/(float(self.h_bunch)*c*self.beta_beam)
        
        
        return parsed_impulse_response, samples, turns, time

