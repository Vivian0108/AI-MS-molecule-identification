"""UnknownID: closed-world, energy-aware LC-ESI-MS/MS identification assistant.

The package deliberately separates three read domains:

* :mod:`unknownid.core.retrieve` / :mod:`unknownid.core.templates` only see the
  static reference library at 10 and 50 eV.
* :mod:`unknownid.simulator.oracle` owns the hidden 20/30/40 eV observations.
* :mod:`unknownid.eval` is the only consumer of ground-truth identity.

Never pass an oracle handle into a planner or candidate scorer.
"""

__version__ = "0.1.0"
