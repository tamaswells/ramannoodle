"""Polarizability models."""

from abc import ABC, abstractmethod

import numpy as np
from numpy.typing import NDArray
from scipy.interpolate import make_interp_spline, BSpline

from . import polarizability_utils
from ..symmetry.symmetry_utils import is_orthogonal_to_all
from ..symmetry import StructuralSymmetry


class PolarizabilityModel(ABC):  # pylint: disable=too-few-public-methods
    """Represents a polarizability model"""

    @abstractmethod
    def get_polarizability(
        self, displacement: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        """Returns a polarizability for a set of atomic displacements."""


class InterpolationPolarizabilityModel(PolarizabilityModel):
    """This model uses interpolation around independent degrees of
    freedom to estimate polarizabilities.
    With linear interpolation + phonon displacements, we get a standard
    raman-tensor-based spectrum.
    With linear interpolation + site displacements, we get an atomic raman
    tensor-based spectrum. This class also needs to take careful care
    to obey symmetry operations.

    """

    def __init__(self, structural_symmetry: StructuralSymmetry) -> None:
        self._structural_symmetry = structural_symmetry
        self._basis_vectors: list[NDArray[np.float64]] = []
        self._interpolations: list[BSpline] = []

    def get_polarizability(
        self, displacement: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        """Returns a polarizability for a given displacement."""

        # Project displacement onto each dof_displacement, use the coordinate to
        # define the interpolation.

        return np.array([])

    def add_dof(  # pylint: disable=too-many-locals
        self,
        displacement: NDArray[np.float64],
        magnitudes: NDArray[np.float64],
        polarizabilities: NDArray[np.float64],
        interpolation_dim: int,
    ) -> None:
        """Adds a degree of freedom"""

        parent_displacement = displacement / (np.linalg.norm(displacement) * 10)

        # Check that the parent displacement is orthogonal to existing basis vectors
        result = is_orthogonal_to_all(parent_displacement, self._basis_vectors)
        if result != -1:
            raise ValueError(
                f"new dof is not orthogonal with existing dof (index={result})"
            )
        if len(magnitudes) == 0:
            raise ValueError("no magnitudes provided")
        if len(magnitudes) != len(polarizabilities):
            raise ValueError(
                f"unequal numbers of magnitudes ({len(magnitudes)})) and "
                f"polarizabilities ({len(polarizabilities)})"
            )

        displacements_and_transformations = (
            self._structural_symmetry.get_equivalent_displacements(parent_displacement)
        )

        basis_vectors_to_add: list[NDArray[np.float64]] = []
        interpolations_to_add: list[BSpline] = []
        for dof_dictionary in displacements_and_transformations:
            child_displacement = dof_dictionary["displacements"][0]

            interpolation_x = []
            interpolation_y = []
            for collinear_displacement, transformation in zip(
                dof_dictionary["displacements"], dof_dictionary["transformations"]
            ):
                _index = np.unravel_index(
                    np.argmax(np.abs(child_displacement)), child_displacement.shape
                )
                multiplier = child_displacement[_index] / collinear_displacement[_index]

                for magnitude, polarizability in zip(magnitudes, polarizabilities):
                    interpolation_x.append(multiplier * magnitude)
                    interpolation_y.append(polarizability @ transformation[0])

            # If duplicate magnitudes are generated, too much data has
            # been provided
            duplicate = polarizability_utils.find_duplicates(interpolation_x)
            if duplicate is not None:
                raise ValueError(
                    f"due to symmetry, magnitude {duplicate} should not be specified"
                )

            if len(interpolation_x) <= interpolation_dim:
                raise ValueError(
                    f"insufficient data ({len(interpolation_x)}) available for"
                    f"{interpolation_dim}-dimensional interpolation"
                )
            assert len(interpolation_x) > 1
            basis_vectors_to_add.append(
                child_displacement / np.linalg.norm(child_displacement)
            )
            sort_indices = np.argsort(interpolation_x)
            interpolations_to_add.append(
                make_interp_spline(
                    x=np.array(interpolation_x)[sort_indices],
                    y=np.array(interpolation_y)[sort_indices],
                    k=interpolation_dim,
                    bc_type=None,
                )
            )

        self._basis_vectors += basis_vectors_to_add
        self._interpolations += interpolations_to_add
