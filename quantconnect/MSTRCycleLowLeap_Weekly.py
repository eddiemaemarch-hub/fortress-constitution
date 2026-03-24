# QuantConnect LEAN Algorithm
# MSTR Cycle-Low LEAP v2.2 — WEEKLY Resolution Variant
# Evaluates entry/exit on weekly bars. Weekly SMA uses weekly data.
# This is the default resolution; included for completeness.

from AlgorithmImports import *
from MSTRCycleLowLeap import MSTRCycleLowLeap


class MSTRCycleLowLeapWeekly(MSTRCycleLowLeap):

    def Initialize(self):
        self.trade_resolution = Resolution.Weekly
        super().Initialize()
