# QuantConnect LEAN Algorithm
# MSTR Cycle-Low LEAP v2.2 — MONTHLY Resolution Variant
# Evaluates entry/exit on monthly bars. Weekly SMA still uses weekly data.

from AlgorithmImports import *
from MSTRCycleLowLeap import MSTRCycleLowLeap


class MSTRCycleLowLeapMonthly(MSTRCycleLowLeap):

    def Initialize(self):
        # Set resolution BEFORE calling super().Initialize() so scheduling uses it
        self.trade_resolution = Resolution.Monthly
        super().Initialize()
