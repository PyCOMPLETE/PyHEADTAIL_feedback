import numpy as np
import itertools
import math



# TODO: Check vector sum of complex numbers
class Averager(object):
    """The simplest possible signal mixer of pick ups, which calculates a phase weighted average of
    the pick up signals"""
    def __init__(self,channel):
        self.channel = channel

    def mix(self,kicker_phase_shift,pickups):
        signal = None

        for index, pickup in enumerate(pickups):
            if signal is None:
                signal = np.zeros(len(pickup.signal_x))

            if self.channel == 'x':
                signal += pickup.signal_x/len(pickups)
            elif self.channel == 'y':
                signal += pickup.signal_y/len(pickups)