import copy, math
import numpy as np
from abc import ABCMeta, abstractmethod

from ..core import Parameters, Signal
from ..core import bin_widths, bin_mids, bin_edges_to_z_bins, z_bins_to_bin_edges
from scipy.constants import c, pi
import scipy.integrate as integrate
import scipy.special as special
from scipy.interpolate import UnivariateSpline
from ..core import debug_extension
from ..core import bin_mids
# TODO: - 2nd order cutoff by using gaussian filter

class Convolution(object):
    __metaclass__ = ABCMeta

    def __init__(self,**kwargs):

        self._dashed_impulse_responses = None
        self._impulses_from_segments = None
        self._impulses_to_segments = None

        self._n_seg = None
        self._n_bins = None

        self.extensions = ['debug']
        self._extension_objects = [debug_extension(self, 'Convolution', **kwargs)]

    def _init_convolution(self, parameters):


        # the parameters of the input signal
        self._n_seg = parameters['n_segments']
        self._n_bins = parameters['n_bins_per_segment']
        bin_edges = parameters['bin_edges']
        n_seg = parameters['n_segments']
        n_bins = parameters['n_bins_per_segment']
#        ref_points = parameters['segment_ref_points']

        # a number of impulse values added to the both side of the segments
        extra_bins = np.ceil(n_bins/2.)

        # Reference bin edges for one segment
        impulse_ref_edges = None

        # ipulse responses for individual segments
        self._dashed_impulse_responses = []

        # impulses caused by the segments
        self._impulses_from_segments = []

        # List of impulses to the corresponding segments
        self._impulses_to_segments = []
        for i in xrange(n_seg):
            self._impulses_to_segments.append([])

        ref_points = []

        for i in xrange(n_seg):
            i_from = i*n_bins
            i_to = (i+1)*n_bins

            # original bins corresponing to the signal
            org_edges = bin_edges[i_from:i_to, :]
            # extra bins before the original bins
            prefix_offset = org_edges[(extra_bins-1), 1]-org_edges[0, 0]
            # extra bins after the original bins
            postfix_offset = org_edges[-extra_bins, 0]-org_edges[-1, 1]

            edges = np.concatenate(((org_edges[:extra_bins]-prefix_offset), org_edges), axis=0)
            edges = np.concatenate((edges, org_edges[extra_bins:]-postfix_offset), axis=0)

            # reference points of the segments, which correspond to midpoint of
            # the bin sets in this case.
            ref_points.append(np.mean(bin_edges_to_z_bins(org_edges)))

            if impulse_ref_edges is None:
                impulse_ref_edges = edges
            else:
                impulse_ref_edges = np.concatenate((impulse_ref_edges, edges), axis=0)

        # calculats the impulse response values for each segment
        for i, ref_point in enumerate(ref_points):
            # sets the zero point of the bin set to be in the middle of the segment
            impulse_edges = impulse_ref_edges-ref_point

            # sets the midpoint of the closest bin to the zero to be zero
            mids = bin_mids(impulse_edges)
            min_max = np.min(mids[mids>=0])
            max_min = np.min(-1.*mids[mids<0])
            mean_width = np.mean(bin_widths(impulse_edges))

            mid_offset = 0.
            idx_offset = 0

            if min(min_max, max_min) < mean_width/10.:
                pass

            elif min_max < max_min:
                if min_max < mean_width:
                    mid_offset = min_max
                    idx_offset = 1
            else:
                if max_min < mean_width:
                    mid_offset = -1 * max_min

            impulse_edges = impulse_edges - mid_offset
            original_segment_length = bin_edges[n_bins-1,1]-bin_edges[0,0]

            # calculates impulse response for the determined bin set
            dashed_impulse_response = self.response_function(impulse_edges, n_seg,
                                                                           original_segment_length)

            cleaned_impulse = np.array([])
            # a list of segment indexes where impulse response is non zero
            target_segments = []

            # cleans the calculated impulse response, i.e. removes the segments where
            # response is zero.
            n_bins_per_segment = n_bins + 2* extra_bins
            for k in xrange(n_seg):
                i_from = k * n_bins_per_segment
                i_to = (k+1) * n_bins_per_segment

                if np.sum(np.abs(dashed_impulse_response[i_from:i_to])) > 0.:
                    target_segments.append(k)
                    cleaned_impulse = np.append(cleaned_impulse, dashed_impulse_response[i_from:i_to])

            self._dashed_impulse_responses.append(cleaned_impulse)

            self._impulses_from_segments.append(np.zeros(len(cleaned_impulse)))
            for idx, target_idx in enumerate(target_segments):
                i_from = idx * n_bins_per_segment + extra_bins + idx_offset
                i_to = idx * n_bins_per_segment + extra_bins + n_bins + idx_offset
                self._impulses_to_segments[target_idx].append(np.array(self._impulses_from_segments[i][i_from:i_to], copy=False))

    @abstractmethod
    def response_function(self, impulse_ref_edges, n_seg, original_segment_length):
        # A function which calculates the impulse response values for the
        # the given bin set
        pass

    def _apply_convolution(self, parameters, signal):

        if self._dashed_impulse_responses is None:
            self._init_convolution(parameters)

        # calculates the impulses caused by the segments
        for i in xrange(self._n_seg):
            i_from = i*self._n_bins
            i_to = (i+1)*self._n_bins
            np.copyto(self._impulses_from_segments[i],
                      np.convolve(self._dashed_impulse_responses[i],
                                  signal[i_from:i_to], mode='same'))

        # gathers the output signal
        output_signal = np.zeros(len(signal))
        for i in xrange(self._n_seg):

            i_from = i*self._n_bins
            i_to = (i+1)*self._n_bins
            np.copyto(output_signal[i_from:i_to], np.sum(self._impulses_to_segments[i], axis=0))

        return output_signal

    def process(self, parameters, signal, *args, **kwargs):

        output_signal = self._apply_convolution(parameters, signal)

        for extension in self._extension_objects:
            extension(self, parameters, signal, parameters, output_signal,
                      *args, **kwargs)

        return parameters, output_signal

class Delay(Convolution):
    def __init__(self,delay, **kwargs):


        self._z_delay = delay*c

        if self._z_delay < 0.:
            impulse_range = (self._z_delay, 0.)
        else:
            impulse_range = (0., self._z_delay)

        super(self.__class__, self).__init__(**kwargs)
        self.label = 'Delay'

    def response_function(self, impulse_ref_edges, n_segments, original_segment_length):
        impulse_values = np.zeros(len(impulse_ref_edges))
        bin_spacing =  np.mean(impulse_ref_edges[:,1]-impulse_ref_edges[:,0])

        ref_bin_from = -0.5*bin_spacing+self._z_delay
        ref_bin_to = 0.5*bin_spacing+self._z_delay

        for i, edges in enumerate(impulse_ref_edges):
            impulse_values[i] = self._CDF(edges[1],ref_bin_from,ref_bin_to) - self._CDF(edges[0],ref_bin_from,ref_bin_to)

        return impulse_values

    def _CDF(self,x,ref_bin_from, ref_bin_to):
        # FIXME: this is not gonna work for nagative delays?

        if x <= ref_bin_from:
            return 0.
        elif x < ref_bin_to:
            return (x-ref_bin_from)/float(ref_bin_to-ref_bin_from)
        else:
            return 1.


class MovingAverage(Convolution):
    """ Returns a signal, which consists an average value of the input signal. A sums of the rows in the matrix
        are normalized to be one (i.e. a sum of the input signal doesn't change).
    """

    def __init__(self,window_length, quantity = 'time', **kwargs):

        if quantity == 'time':
            self._window = (-0.5 * window_length * c, 0.5 * window_length * c)
        elif quantity == 'distance':
            self._window = (-0.5 * window_length, 0.5 * window_length)
        else:
            raise ValueError('Unknown value in Average.quantity')

        super(self.__class__, self).__init__(**kwargs)
        self.label = 'Average'

    def response_function(self, impulse_ref_edges, n_segments, original_segment_length):
        impulse_values = np.zeros(len(impulse_ref_edges))

        for i, edges in enumerate(impulse_ref_edges):
            impulse_values[i] = self._CDF(edges[1], self._window[0], self._window[1]) \
                                   - self._CDF(edges[0], self._window[0], self._window[1])

        return impulse_values

    def _CDF(self, x, ref_bin_from, ref_bin_to):
        if x <= ref_bin_from:
            return 0.
        elif x < ref_bin_to:
            return (x - ref_bin_from) / float(ref_bin_to - ref_bin_from)
        else:
            return 1.


class WaveletGenerator(Convolution):

    def __init__(self,spacing,n_copies, **kwargs):
        self._spacing = spacing
        self._n_copies = n_copies

        if isinstance(self._n_copies,tuple):
            self._i_from = self._n_copies[0]
            self._i_to = self._n_copies[1]

        else:
            self._i_from = min(self._n_copies,0)
            self._i_to = max(self._n_copies,0)

        self._window = (self._i_from*self._spacing*c,self._i_to*self._spacing*c)

        super(self.__class__, self).__init__(**kwargs)
        self.label = 'Wavelet generator'


    def response_function(self, impulse_ref_edges, n_segments, original_segment_length):
#    def calculate_response(self, impulse_bin_mids, impulse_bin_edges):
        impulse_bin_mids = bin_mids(impulse_ref_edges)
        bin_spacing = np.mean(impulse_ref_edges[:,1]-impulse_ref_edges[:,0])
        impulse_values = np.zeros(len(impulse_bin_mids))

        for i in xrange(self._i_from,(self._i_to+1)):
            copy_mid = i*self._spacing*c
            copy_from = copy_mid - 0.5 * bin_spacing
            copy_to = copy_mid + 0.5 * bin_spacing

            for j, edges in enumerate(impulse_ref_edges):
                impulse_values[j] += (self._CDF(edges[1],copy_from,copy_to)-self._CDF(edges[0],copy_from,copy_to))

        return impulse_values


    def _CDF(self, x, ref_bin_from, ref_bin_to):
        if x <= ref_bin_from:
            return 0.
        elif x < ref_bin_to:
            return (x - ref_bin_from) / float(ref_bin_to - ref_bin_from)
        else:
            return 1.
#
#class ConvolutionFromFile(Convolution):
#    """ Interpolates matrix columns by using inpulse response data from a file. """
#
#    def __init__(self,filename, x_axis = 'time', calc_type = 'mean',  **kwargs):
#        self._filename = filename
#        self._x_axis = x_axis
#        self._calc_type = calc_type
#
#        self._data = np.loadtxt(self._filename)
#        if self._x_axis == 'time':
#            self._data[:, 0]=self._data[:, 0]*c
#
#        impulse_range = (self._data[0,0],self._data[-1,0])
#
#        super(self.__class__, self).__init__(impulse_range, **kwargs)
#        self.label = 'Convolution from external data'
#
#    def calculate_response(self, impulse_response_bin_mid, impulse_response_bin_edges):
#
#        if self._calc_type == 'mean':
#            return np.interp(impulse_response_bin_mid, self._data[:, 0], self._data[:, 1])
#        elif self._calc_type == 'integral':
#            s = UnivariateSpline(self._data[:, 0], self._data[:, 1])
#            response_values = np.zeros(len(impulse_response_bin_mid))
#
#            for i, edges in enumerate(impulse_response_bin_edges):
#                response_values[i], _ = s.integral(edges[0],edges[1])
#            return response_values
#
#        else:
#            raise ValueError('Unknown value in ConvolutionFromFile._calc_type')

class ConvolutionFilter(Convolution):
    """ An abstract class for the filtes based on convolution."""

    __metaclass__ = ABCMeta

    def __init__(self,scaling,impulse_range,zero_bin_value = None, tip_cut_width=None,
                 normalization=None, **kwargs):

        self._scaling = scaling
        self._normalization = normalization

        self._zero_bin_value = zero_bin_value
        super(ConvolutionFilter, self).__init__(**kwargs)
        self.label='ConvolutionFilter'
        # NOTE: is the tip cut needed? How to work with the sharp tips of the ideal filters?
        if (self._normalization is None) and (tip_cut_width is not None):
            self._normalization = 'integral'
        self._impulse_response = self._impulse_response_generator(tip_cut_width)

    def response_function(self, impulse_ref_edges, n_segments, original_segment_length):
        impulse = np.zeros(len(impulse_ref_edges))

        for i, edges in enumerate(impulse_ref_edges):
            # normalizes the edges to dimensioles units
            integral_from = edges[0] * self._scaling
            integral_to = edges[1] * self._scaling

            # calculates the impulse value for the bin by integrating the impulse
            # response over the normalized bin
            impulse[i], _ = integrate.quad(self._impulse_response, integral_from, integral_to)

        # normalizes the impulse response
        impulse = self._normalize(impulse_ref_edges, impulse, original_segment_length)

        # searches the zero bin and adds it the set zero bin value if it is
        # determined
        if self._zero_bin_value is not None:
            for i, edges in enumerate(impulse_ref_edges):
                if (edges[0] <= 0.) and (0. < edges[1]):
                    impulse[i] = impulse_ref_edges[i] + self._zero_bin_value

        return impulse

    def _normalize(self, impulse_ref_edges, impulse, segment_length):

        if self._normalization is None:
            pass
        elif isinstance(self._normalization, tuple):
            if self._normalization[0] == 'integral':
                norm_coeff, _ = integrate.quad(self._impulse_response, self._normalization[1][0], self._normalization[1][1])
                impulse = impulse/norm_coeff
            elif self._normalization[0] == 'bunch_by_bunch':
                f_h = self._normalization[1]

                norm_coeff = 0.
                for i in xrange(-1000,1000):
                    x = float(i)* (1./f_h) * self._scaling * c
                    norm_coeff += self._impulse_response(x)
                #print norm_coeff
                #print x
                #print self._normalization[1] * self._scaling * c
                #print self._normalization[1] * c
                impulse = impulse/norm_coeff/(segment_length * self._scaling)



            else:
                raise ValueError('Unknown normalization method!')
        elif self._normalization == 'sum':
            impulse = impulse/np.sum(impulse)

        else:
            raise ValueError('Unknown normalization method!')

        return impulse
#
#        if self._normalization is None:
#            pass
#        elif isinstance(self._normalization, float):
#            impulse_values = impulse_values/self._normalization
#        elif isinstance(self._normalization, tuple):
#            if self._normalization[0] == 'bunch_by_bunch':
#                bunch_spacing = self._normalization[1] * c
#
#                bunch_locations = np.array([])
#                if (impulse_bin_edges[0,0] < 0):
#                    bunch_locations = np.append(bunch_locations, -1.*np.arange(0.,-1.*impulse_bin_edges[0,0],bunch_spacing))
#                if (impulse_bin_edges[-1,1] > 0):
#                    bunch_locations = np.append(bunch_locations, np.arange(0.,impulse_bin_edges[-1,1],bunch_spacing))
#
#                bunch_locations = np.unique(bunch_locations)
#
#                min_mask = (bunch_locations >= impulse_bin_edges[0,0])
#                max_mask = (bunch_locations <= impulse_bin_edges[-1,1])
#
#                bunch_locations = bunch_locations[min_mask*max_mask]
#
#                total_sum = 0.
#
#                # TODO: check, which is the best way to calculate the normalization coefficient
#                total_sum = np.sum(np.interp([bunch_locations], impulse_bin_mids, impulse_values))
##                for location in bunch_locations:
##                    min_mask = (impulse_bin_mids > (location - bunch_length/2.))
##                    max_mask = (impulse_bin_mids < (location + bunch_length/2.))
##
##                    total_sum += np.mean(impulse_values[min_mask*max_mask])
#
#                impulse_values = impulse_values/total_sum
#
#            else:
#                raise ValueError('Unknown normalization method')
#
#        elif self._normalization == 'max':
#            impulse_values = impulse_values/np.max(impulse_values)
#        elif self._normalization == 'min':
#            impulse_values = impulse_values/np.min(impulse_values)
#        elif self._normalization == 'average':
#            impulse_values = impulse_values/np.abs(np.mean(impulse_values))
#        elif self._normalization == 'sum':
#            # TODO: check naming, this is not a sum, but an integral?
#            impulse_values = impulse_values/np.abs(np.sum(impulse_values))
#        elif self._normalization == 'integral':
#            bin_widths = impulse_bin_edges[:,1]-impulse_bin_edges[:,0]
#            impulse_values = impulse_values / np.abs(np.sum(impulse_values*bin_widths))
#        else:
#            raise ValueError('Unknown normalization method')
#
#        if self._zero_bin_value is not None:
#            for i, edges in enumerate(impulse_bin_edges):
#                if (edges[0] <= 0.) and (0. < edges[1]):
#                    impulse_values[i] = impulse_values[i] + self._zero_bin_value
#
#        return impulse_values

    @abstractmethod
    def _raw_impulse_response(self, x):
        """ Impulse response of the filter.
        :param x: normalized time (t*2.*pi*f_c)
        :return: response at the given time
        """
        pass

    def _impulse_response_generator(self,tip_cut_width):
        """ A function which generates the response function from the raw impulse response. If 2nd cut-off frequency
            is given, the value of the raw impulse response is set to constant at the time scale below that.
            The integral over the response function is normalized to value 1.
        """

        if tip_cut_width is not None:
            def transfer_function(x):
                if np.abs(x) < tip_cut_width:
                    return self._raw_impulse_response(np.sign(x)*tip_cut_width)
                else:
                    return self._raw_impulse_response(x)
        else:
            def transfer_function(x):
                    return self._raw_impulse_response(x)

        return transfer_function


class Lowpass(ConvolutionFilter):
    """ A classical lowpass filter, which is also known as a RC-filter or one
        poll roll off.
    """
    def __init__(self,f_cutoff, impulse_length = 5., f_cutoff_2nd = None, normalization=('integral',(-5.,5.)), **kwargs):
        scaling = 2. * pi * f_cutoff / c
        impulse_range = (0, impulse_length/scaling)

        if f_cutoff_2nd is not None:
            tip_cut_width = f_cutoff / f_cutoff_2nd
        else:
            tip_cut_width = None

        super(self.__class__, self).__init__(scaling, impulse_range, tip_cut_width = tip_cut_width, normalization=normalization,**kwargs)
        self.label = 'Lowpass filter'

    def _raw_impulse_response(self, x):
        if x < 0.:
            return 0.
        else:
            return math.exp(-1. * x)

class Highpass(ConvolutionFilter):
    """ A high pass version of the lowpass filter, which is constructed by
        multiplying the lowpass filter by a factor of -1 and adding to the first
        bin 1
    """
    def __init__(self,f_cutoff, impulse_length = 5., f_cutoff_2nd = None, normalization=('integral',(-5.,5.)), **kwargs):
        scaling = 2. * pi * f_cutoff / c
        impulse_range = (0, impulse_length/scaling)

        if f_cutoff_2nd is not None:
            tip_cut_width = f_cutoff / f_cutoff_2nd
        else:
            tip_cut_width = None

        super(self.__class__, self).__init__( scaling, impulse_range, zero_bin_value= 1., tip_cut_width = tip_cut_width, normalization=normalization, **kwargs)
        self.label = 'Highpass filter'

    def _raw_impulse_response(self, x):
        if x < 0.:
            return 0.
        else:
            return -1.* math.exp(-1. * x)

class PhaseLinearizedLowpass(ConvolutionFilter):
    """ A phase linearized 1st order lowpass filter. Note that the narrow and
        sharp peak of the impulse response makes the filter to be sensitive
        to the bin width and may yield an unrealistically good response for the
        short signals. Thus it is recommended to set a second order cut off
        frequency, which smooths the impulse response by using a Gaussian filter.
    """

    def __init__(self, f_cutoff, impulse_length = 5., f_cutoff_2nd = None, normalization=('integral',(-5.,5.)), **kwargs):
        scaling = 2. * pi * f_cutoff / c
        impulse_range = (-1.*impulse_length/scaling, impulse_length/scaling)

        if f_cutoff_2nd is not None:
            tip_cut_width = f_cutoff / f_cutoff_2nd
        else:
            tip_cut_width = None

        super(self.__class__, self).__init__( scaling, impulse_range, tip_cut_width = tip_cut_width, normalization=normalization, **kwargs)
        self.label = 'Phaselinearized lowpass filter'

    def _raw_impulse_response(self, x):
        if x == 0.:
            return 0.
        else:
            return special.k0(abs(x))


class Gaussian(ConvolutionFilter):
    """ A Gaussian low pass filter, which impulse response is a Gaussian function.
    """
    def __init__(self, f_cutoff, impulse_length = 5., normalization=('integral',(-5.,5.)), **kwargs):
        scaling = 2. * pi * f_cutoff / c
        impulse_range = (-1.*impulse_length/scaling, impulse_length/scaling)


        tip_cut_width = None

        super(self.__class__, self).__init__( scaling, impulse_range, tip_cut_width = tip_cut_width, normalization=normalization, **kwargs)
        self.label = 'Gaussian lowpass filter'

    def _raw_impulse_response(self, x):
        return np.exp(-x ** 2. / 2.) / np.sqrt(2. * pi)


class Sinc(ConvolutionFilter):
    """ A nearly ideal lowpass filter, i.e. a windowed Sinc filter. The impulse response of the ideal lowpass filter
        is Sinc function, but because it is infinite length in both positive and negative time directions, it can not be
        used directly. Thus, the length of the impulse response is limited by using windowing. Properties of the filter
        depend on the width of the window and the type of the windows and must be written down. Too long window causes
        ripple to the signal in the time domain and too short window decreases the slope of the filter in the frequency
        domain. The default values are a good compromise. More details about windowing can be found from
        http://www.dspguide.com/ch16.htm and different options for the window can be visualized, for example, by using
        code in example/test 004_analog_signal_processors.ipynb
    """

    def __init__(self, f_cutoff, window_width = 3, window_type = 'blackman', normalization=('integral',(-10.,10.)), **kwargs):
        """
        :param f_cutoff: a cutoff frequency of the filter
        :param delay: a delay of the filter [s]
        :param window_width: a (half) width of the window in the units of zeros of Sinc(x) [2*pi*f_c]
        :param window_type: a shape of the window, blackman or hamming
        :param norm_type: see class LinearTransform
        :param norm_range: see class LinearTransform
        """

        scaling = 2. * pi * f_cutoff / c

        self.window_width = float(window_width)
        self.window_type = window_type
        impulse_range = (-1.*pi *window_width/scaling, pi*window_width/scaling)
        super(self.__class__, self).__init__(scaling, impulse_range,normalization=normalization, **kwargs)
        self.label = 'Sinc filter'

    def _raw_impulse_response(self, x):
        if np.abs(x/pi) > self.window_width:
            return 0.
        else:
            if self.window_type == 'blackman':
                return np.sinc(x/pi)*self.blackman_window(x)
            elif self.window_type == 'hamming':
                return np.sinc(x/pi)*self.hamming_window(x)

    def blackman_window(self,x):
        return 0.42-0.5*np.cos(2.*pi*(x/pi+self.window_width)/(2.*self.window_width))\
               +0.08*np.cos(4.*pi*(x/pi+self.window_width)/(2.*self.window_width))

    def hamming_window(self, x):
        return 0.54-0.46*np.cos(2.*pi*(x/pi+self.window_width)/(2.*self.window_width))



class FIRFilter(Convolution):

    def __init__(self, coefficients, zero_tap = 0, **kwargs):

        self._zero_tap = zero_tap

        self._input_coefficients = coefficients

        super(FIRFilter, self).__init__(**kwargs)
        self.label = 'FIR filter'


    def response_function(self, impulse_ref_edges, n_segments, original_segment_length):
        impulse = np.zeros(len(impulse_ref_edges))
        impulse_bin_widths = bin_widths(impulse_ref_edges)
        impulse_bin_width = np.mean(impulse_bin_widths)
        impulse_bin_mids = bin_mids(impulse_ref_edges)

        n_coefficients = len(self._input_coefficients)
        min_filter_idx = -1*self._zero_tap
        max_filter_idx = min_filter_idx + n_coefficients -1

        for i, mid in enumerate(impulse_bin_mids):
            filter_idx = mid/impulse_bin_width
            filter_idx = int(np.round(filter_idx))

            if (filter_idx >= min_filter_idx) and (filter_idx <= max_filter_idx):
                impulse[i] = self._input_coefficients[filter_idx+self._zero_tap]

        return impulse