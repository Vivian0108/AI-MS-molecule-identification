"""Deterministic fragment-formula evidence for SpectraPilot v3.

Two things are deliberately kept apart:

* **Peak explanation** — for a *candidate formula hypothesis*, which observed
  peaks admit a chemically valid charged sub-formula?  This is computed by
  MSBuddy's ``assign_subformula``, which handles positive-mode adduct and
  radical-ion bookkeeping.  It is never run on the true (unknown) formula.
* **Neutral-loss plausibility** — is a matched neutral loss the mass of *some*
  sub-formula of the candidate?  This is a necessary condition only.

Scientific guardrails enforced here:

* A fragment formula does **not** determine a bond-cleavage pathway or a
  connectivity.  Same-formula isomers explain the same formula-level peaks, so
  this evidence is only useful against distractors with a different formula.
* MSBuddy's ion bookkeeping is CID-oriented.  EAD is radical/electron-driven, so
  EAD sub-formula evidence is reported as unavailable rather than "validated".
* Missing backend -> ``None`` features, never a fabricated zero.
"""

from __future__ import annotations

import functools
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

# Monoisotopic masses (Da).  Kept local so the feature layer never depends on a
# particular MSBuddy release for mass arithmetic.
MONO: dict[str, float] = {
    "C": 12.0,
    "H": 1.00782503223,
    "N": 14.00307400443,
    "O": 15.99491461957,
    "P": 30.97376199842,
    "S": 31.97207117440,
    "F": 18.99840316273,
    "Cl": 34.96885268200,
    "Br": 78.91833760000,
    "I": 126.90447190000,
}
ELEMENTS = ("C", "H", "N", "O", "P", "S", "F", "Cl", "Br", "I")
ELECTRON_MASS = 0.00054857990907
PROTON_MASS = 1.007276466621


def parse_formula(formula: str) -> dict[str, int]:
    """Parse a Hill-style formula.  Raises on unsupported elements."""
    counts: dict[str, int] = {}
    index = 0
    text = str(formula or "").strip()
    while index < len(text):
        char = text[index]
        if not char.isupper():
            raise ValueError(f"invalid formula {formula!r} at {index}")
        end = index + 1
        while end < len(text) and text[end].islower():
            end += 1
        symbol = text[index:end]
        if symbol not in MONO:
            raise ValueError(f"unsupported element {symbol!r} in {formula!r}")
        index = end
        digits = ""
        while index < len(text) and text[index].isdigit():
            digits += text[index]
            index += 1
        counts[symbol] = counts.get(symbol, 0) + (int(digits) if digits else 1)
    if not counts:
        raise ValueError(f"empty formula {formula!r}")
    return counts


def formula_str(counts: dict[str, int]) -> str:
    """Hill-order formula string, omitting zero counts."""
    parts = []
    for symbol in ("C", "H") + tuple(e for e in ELEMENTS if e not in {"C", "H"}):
        count = int(counts.get(symbol, 0))
        if count <= 0:
            continue
        parts.append(symbol if count == 1 else f"{symbol}{count}")
    return "".join(parts)


def formula_mass(counts: dict[str, int]) -> float:
    return float(sum(MONO[symbol] * int(count) for symbol, count in counts.items()))


def is_subformula(sub: dict[str, int], parent: dict[str, int]) -> bool:
    return all(int(sub.get(symbol, 0)) <= int(parent.get(symbol, 0)) for symbol in sub)


def ring_double_bond_equivalent(counts: dict[str, int]) -> float:
    """RDBE including halogens; radical ions are allowed a half-integer value."""
    c = counts.get("C", 0)
    h = counts.get("H", 0)
    n = counts.get("N", 0)
    x = sum(counts.get(el, 0) for el in ("F", "Cl", "Br", "I"))
    return c - (h + x) / 2.0 + n / 2.0 + 1.0


@functools.lru_cache(maxsize=4096)
def _subformula_masses_cached(formula: str, max_mass_x1000: int) -> tuple[float, ...]:
    """All sub-formula exact masses of ``formula`` up to a mass cap.

    A vectorised element-by-element convolution with pruning.  Used only for a
    necessary-condition test on neutral losses.
    """
    parent = parse_formula(formula)
    cap = max_mass_x1000 / 1000.0
    masses = np.zeros(1, dtype=float)
    for symbol in ELEMENTS:
        limit = int(parent.get(symbol, 0))
        offsets = MONO[symbol] * np.arange(limit + 1, dtype=float)
        masses = (masses[:, None] + offsets[None, :]).ravel()
        masses = masses[masses <= cap]
        if masses.size == 0:
            return ()
    masses = np.unique(np.round(masses, 6))
    return tuple(float(value) for value in masses)


def subformula_masses(formula: str, *, max_mass: float) -> np.ndarray:
    values = _subformula_masses_cached(formula, int(round(max_mass * 1000)))
    return np.asarray(values, dtype=float)


def _option_strings(formula: str, masses: np.ndarray) -> list[str]:
    parent = parse_formula(formula)
    out: list[str] = []
    for value in masses:
        # Recover a plausible sub-formula by a bounded greedy search.  Only used
        # for human-readable hypothesis cards, never for scoring.
        counts = _greedy_formula(parent, float(value))
        if counts is not None:
            out.append(formula_str(counts))
    return out


def _greedy_formula(parent: dict[str, int], mass: float, tol: float = 0.01) -> dict[str, int] | None:
    remaining = float(mass)
    counts: dict[str, int] = {}
    for symbol in ELEMENTS:
        limit = int(parent.get(symbol, 0))
        if limit <= 0:
            continue
        take = min(limit, int(remaining // MONO[symbol]))
        while take > 0 and remaining - take * MONO[symbol] < -tol:
            take -= 1
        if take > 0:
            counts[symbol] = take
            remaining -= take * MONO[symbol]
    if abs(remaining) <= tol and counts:
        return counts
    return None


@dataclass
class PeakExplanation:
    """Per-peak formula explanation for one candidate formula hypothesis."""

    n_observed_peaks: int
    n_explained: int
    n_contradicted: int
    explained_intensity_fraction: float
    unexplained_intensity_fraction: float
    per_peak_options: list[list[str]] = field(default_factory=list)
    backend: str = "msbuddy"
    method_validated: bool = True

    def public_dict(self) -> dict:
        return {
            "n_observed_peaks": self.n_observed_peaks,
            "n_explained": self.n_explained,
            "n_contradicted": self.n_contradicted,
            "explained_intensity_fraction": self.explained_intensity_fraction,
            "unexplained_intensity_fraction": self.unexplained_intensity_fraction,
            "backend": self.backend,
            "method_validated": self.method_validated,
        }


class SubformulaBackend:
    """MSBuddy adapter with caching and an explicit availability flag.

    ``available`` is False when the package is missing or fails to load.  In that
    case every feature derived from it is ``None``; the system never substitutes
    a fabricated value.
    """

    #: MSBuddy's ion bookkeeping is validated for CID, not for EAD.
    validated_methods = frozenset({"CID"})

    def __init__(self, *, ppm_tolerance: float = 10.0, enabled: bool | None = None) -> None:
        self.ppm_tolerance = float(ppm_tolerance)
        self._assign = None
        self._availability_checked = False
        self._enabled = enabled
        self._cache: dict[tuple, list[int] | None] = {}
        self.notes: list[str] = []

    # -- lifecycle ---------------------------------------------------------
    @property
    def available(self) -> bool:
        if self._enabled is False:
            return False
        self._ensure()
        return self._assign is not None

    def _ensure(self) -> None:
        if self._availability_checked:
            return
        self._availability_checked = True
        try:  # pragma: no cover - depends on optional dependency
            from msbuddy import assign_subformula  # type: ignore

            # Warm-up call: the first invocation compiles numba helpers.
            assign_subformula([100.0], "C6H12O6", "[M+H]+", ms2_tol=self.ppm_tolerance, ppm=True)
            self._assign = assign_subformula
            self.notes.append("msbuddy subformula assignment enabled")
        except Exception as exc:  # pragma: no cover
            self._assign = None
            self.notes.append(f"msbuddy unavailable: {type(exc).__name__}: {exc}")

    def method_supported(self, fragmentation: str) -> bool:
        return str(fragmentation).upper() in self.validated_methods

    # -- peak explanation --------------------------------------------------
    def explain_peaks(
        self,
        mz: np.ndarray,
        intensity: np.ndarray,
        *,
        formula: str,
        adduct: str,
        fragmentation: str,
    ) -> PeakExplanation | None:
        """Fraction of observed peaks explainable by ``formula``.

        Returns ``None`` when the backend is unavailable or the method is not
        validated, so the caller records a *missing* feature.
        """
        if not self.available or not self.method_supported(fragmentation):
            return None
        mz = np.asarray(mz, float)
        intensity = np.asarray(intensity, float)
        if mz.size == 0:
            return None
        key = (
            formula,
            adduct,
            self.ppm_tolerance,
            tuple(np.round(mz, 4).tolist()),
        )
        if key not in self._cache:
            try:
                results = self._assign(
                    mz.tolist(),
                    formula,
                    adduct,
                    ms2_tol=self.ppm_tolerance,
                    ppm=True,
                )
            except Exception:
                self._cache[key] = None
            else:
                options: list[int] = []
                for item in results or []:
                    options.append(0 if not item.subform_list else len(item.subform_list))
                self._cache[key] = options
        options = self._cache[key]
        if options is None or len(options) != mz.size:
            return None
        explained = np.asarray([count > 0 for count in options], bool)
        total_intensity = float(intensity.sum()) or 1.0
        explained_fraction = float(intensity[explained].sum() / total_intensity)
        return PeakExplanation(
            n_observed_peaks=int(mz.size),
            n_explained=int(explained.sum()),
            n_contradicted=int((~explained).sum()),
            explained_intensity_fraction=explained_fraction,
            unexplained_intensity_fraction=1.0 - explained_fraction,
            per_peak_options=[[] for _ in range(int(mz.size))],
            backend="msbuddy",
            method_validated=True,
        )

    # -- neutral losses ----------------------------------------------------
    def loss_is_plausible(self, loss_mass: float, *, formula: str, tolerance_da: float = 0.02) -> bool | None:
        """True if ``loss_mass`` equals some sub-formula mass of ``formula``.

        Necessary condition only: a chemically plausible loss does not prove the
        proposed fragmentation pathway.
        """
        try:
            masses = subformula_masses(formula, max_mass=loss_mass + tolerance_da)
        except ValueError:
            return None
        if masses.size == 0:
            return False
        index = int(np.searchsorted(masses, loss_mass))
        for candidate in (index - 1, index):
            if 0 <= candidate < masses.size and abs(masses[candidate] - loss_mass) <= tolerance_da:
                return True
        return False
