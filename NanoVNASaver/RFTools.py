#  NanoVNASaver
#
#  A python program to view and export Touchstone data from a NanoVNA
#  Copyright (C) 2019, 2020  Rune B. Broberg
#  Copyright (C) 2020 NanoVNA-Saver Authors
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.
import math
import cmath
from threading import Lock
from typing import Iterator, List, NamedTuple, Tuple

from scipy.interpolate import interp1d

from NanoVNASaver.SITools import clamp_value


class Datapoint(NamedTuple):
    freq: int
    re: float
    im: float

    @property
    def z(self) -> complex:
        """ return the datapoint impedance as complex number """
        return complex(self.re, self.im)

    @property
    def phase(self) -> float:
        """ return the datapoint's phase value """
        return cmath.phase(self.z)

    @property
    def gain(self) -> float:
        mag = abs(self.z)
        if mag > 0:
            return 20 * math.log10(mag)
        return -math.inf

    @property
    def vswr(self) -> float:
        mag = abs(self.z)
        if mag == 1:
            return 1
        return (1 + mag) / (1 - mag)

    @property
    def wavelength(self) -> float:
        return 299792458 / self.freq

    def impedance(self, ref_impedance: float = 50) -> complex:
        return gamma_to_impedance(self.z, ref_impedance)

    def qFactor(self, ref_impedance: float = 50) -> float:
        imp = self.impedance(ref_impedance)
        if imp.real == 0.0:
            return -1
        return abs(imp.imag / imp.real)

    def capacitiveEquivalent(self, ref_impedance: float = 50) -> float:
        return impedance_to_capacitance(self.impedance(ref_impedance), self.freq)

    def inductiveEquivalent(self, ref_impedance: float = 50) -> float:
        return impedance_to_inductance(self.impedance(ref_impedance), self.freq)


class DataSet():
    def __init__(self, fields=("11", "21")):
        self.fields = fields
        self.data = {}
        self.interp = []
        self.inter_valid = False
        self.lock = Lock()

    def copy(self)-> 'Dataset':
        ds = DataSet(self.fields)
        ds.data = self.data.copy()
        ds.inter_valid = False
        return ds

    def insert(self, datapoints: List['Datapoint']):
        assert len(datapoints) == len(self.fields)
        assert len(set([dp.freq for dp in datapoints])) == 1
        frequency = datapoints[0].freq
        self.data[frequency] = [dp.z for dp in datapoints]
        self.inter_valid = False

    def insert_complex(self, frequency: int, data: Tuple[complex]):
        assert len(data) == len(self.fields)
        self.data[frequency] = data
        self.inter_valid = False

    def items(self) -> Iterator[List['Datapoint']]:
        for freq in sorted(self.data.keys()):
            yield [Datapoint(freq, z.real, z.imag) for z in self.data[freq]]

    def items_field(self, field) -> Iterator['Datapoint']:
        i = self.fields.index(field)
        for freq in sorted(self.data.keys()):
            yield Datapoint(freq,
                            self.data[freq][i].real,
                            self.data[freq][i].imag)

    def items_complex(self) -> Iterator[Tuple[int, List[complex]]]:
        for freq in sorted(self.data.keys()):
            yield (freq, self.data[freq])

    def min_freq(self) -> int:
        return min(self.data.keys())

    def max_freq(self) -> int:
        return max(self.data.keys())

    def gen_interpolation(self):
        for i in range(len(self.fields)):
            freqs = []
            reals = []
            imags = []
            for freq, data in self.items_complex():
                freqs.append(freq)
                reals.append(data[i].real)
                imags.append(data[i].imag)
            self.interp.append((
                interp1d(freqs, reals, kind="slinear",
                         fill_value=(reals[0], reals[-1]),
                         bounds_error=False),
                interp1d(freqs, imags, kind="slinear",
                         fill_value=(imags[0], imags[-1]),
                         bounds_error=False)))
        self.inter_valid = True

    def freq(self, freq: int) -> List['Datapoint']:
        if not self.inter_valid:
            self.gen_interpolation()
        return [Datapoint(freq, float(i[0](freq)), float(i[1](freq)))
                for i in self.interp]

    def freq_complex(self, freq: int) -> List[complex]:
        if not self.inter_valid:
            self.gen_interpolation()
        return [complex(float(i[0](freq)), float(i[1](freq)))
                for i in self.interp]

    def freq_field(self, freq: int, field) -> 'Datapoint':
        if not self.inter_valid:
            self.gen_interpolation()
        i = self.interp[self.fields.index(field)]
        return Datapoint(freq, float(i[0](freq)), float(i[1](freq)))

    def freq_field_complex(self, freq: int, field) -> complex:
        if not self.inter_valid:
            self.gen_interpolation()
        i = self.interp[self.fields.index(field)]
        return complex(float(i[0](freq)), float(i[1](freq)))


def gamma_to_impedance(gamma: complex, ref_impedance: float = 50) -> complex:
    """Calculate impedance from gamma"""
    try:
        return ((-gamma - 1) / (gamma - 1)) * ref_impedance
    except ZeroDivisionError:
        return math.inf


def groupDelay(data: List[Datapoint], index: int) -> float:
    idx0 = clamp_value(index - 1, 0, len(data) - 1)
    idx1 = clamp_value(index + 1, 0, len(data) - 1)
    delta_angle = data[idx1].phase - data[idx0].phase
    delta_freq = data[idx1].freq - data[idx0].freq
    if delta_freq == 0:
        return 0
    val = -delta_angle / math.tau / delta_freq
    return val


def impedance_to_capacitance(z: complex, freq: float) -> float:
    """Calculate capacitive equivalent for reactance"""
    if freq == 0:
        return -math.inf
    if z.imag == 0:
        return math.inf
    return -(1 / (freq * 2 * math.pi * z.imag))


def impedance_to_inductance(z: complex, freq: float) -> float:
    """Calculate inductive equivalent for reactance"""
    if freq == 0:
        return 0
    return z.imag * 1 / (freq * 2 * math.pi)


def impedance_to_norm(z: complex, ref_impedance: float = 50) -> complex:
    """Calculate normalized z from impedance"""
    return z / ref_impedance


def norm_to_impedance(z: complex, ref_impedance: float = 50) -> complex:
    """Calculate impedance from normalized z"""
    return z * ref_impedance


def parallel_to_serial(z: complex) -> complex:
    """Convert parallel impedance to serial impedance equivalent"""
    z_sq_sum = z.real ** 2 + z.imag ** 2
    return complex(z.real * z.imag ** 2 / z_sq_sum,
                   z.real ** 2 * z.imag / z_sq_sum)


def reflection_coefficient(z: complex, ref_impedance: float = 50) -> complex:
    """Calculate reflection coefficient for z"""
    return (z - ref_impedance) / (z + ref_impedance)


def serial_to_parallel(z: complex) -> complex:
    """Convert serial impedance to parallel impedance equivalent"""
    z_sq_sum = z.real ** 2 + z.imag ** 2
    if z.real == 0 and z.imag == 0:
        return complex(math.inf, math.inf)
    if z.imag == 0:
        return complex(z_sq_sum / z.real, math.copysign(math.inf, z_sq_sum))
    if z.real == 0:
        return complex(math.copysign(math.inf, z_sq_sum), z_sq_sum / z.imag)
    return complex(z_sq_sum / z.real, z_sq_sum / z.imag)


def corr_att_data(data: List[Datapoint], att: float) -> List[Datapoint]:
    """Correct the ratio for a given attenuation on s21 input"""
    if att <= 0:
        return data
    else:
        att = 10**(att/20)
    ndata = []
    for dp in data:
        corrected = dp.z * att
        ndata.append(Datapoint(dp.freq, corrected.real, corrected.imag))
    return ndata
