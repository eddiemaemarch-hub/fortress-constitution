# QuantConnect LEAN Algorithm
# MSTR Cycle-Low LEAP v2.2 — DAILY Resolution Variant
# Evaluates entry/exit on daily bars. Weekly SMA still uses weekly data.

from AlgorithmImports import *
from MSTRCycleLowLeap import MSTRCycleLowLeap


class MSTRCycleLowLeapDaily(MSTRCycleLowLeap):

    def Initialize(self):
        # Set resolution BEFORE calling super().Initialize() so scheduling uses it
        self.trade_resolution = Resolution.Daily
        super().Initialize()
