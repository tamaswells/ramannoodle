"""Polarizability model based on interpolation around degrees of freedom."""

# This is not ideal, but is required for Python 3.10 support.
# In future versions, we can use "from typing import Self"
from __future__ import annotations

from pathlib import Path
import copy
from typing import Iterable
from warnings import warn
import itertools

import numpy as np
from numpy.typing import NDArray, ArrayLike
from scipy.interpolate import make_interp_spline, BSpline

from ramannoodle.globals import AnsiColors
from ramannoodle.polarizability import PolarizabilityModel
from ramannoodle.symmetry.structural_utils import (
    is_orthogonal_to_all,
    calculate_displacement,
    is_collinear_with_all,
)
from ramannoodle.symmetry.structural import ReferenceStructure
from ramannoodle.exceptions import (
    InvalidDOFException,
    get_type_error,
    verify_ndarray_shape,
    DOFWarning,
)
from ramannoodle import io
from ramannoodle.io.io_utils import pathify_as_list


def get_amplitude(
    cartesian_basis_vector: NDArray[np.float64],
    cartesian_displacement: NDArray[np.float64],
) -> float:
    """Get amplitude of a displacement in angstroms."""
    return float(
        np.dot(cartesian_basis_vector.flatten(), cartesian_displacement.flatten())
    )


def find_duplicates(vectors: Iterable[ArrayLike]) -> NDArray | None:
    """Return duplicate vector in a list or None if no duplicates found.

    :meta private:
    """
    try:
        combinations = itertools.combinations(vectors, 2)
    except TypeError as exc:
        raise get_type_error("vectors", vectors, "Iterable") from exc
    try:
        for vector_1, vector_2 in combinations:
            if np.isclose(vector_1, vector_2).all():
                return np.array(vector_1)
        return None
    except TypeError as exc:
        raise TypeError("elements of vectors are not array_like") from exc


class InterpolationModel(PolarizabilityModel):
    """Polarizability model based on interpolation around degrees of freedom.

    One is free to specify the interpolation order as well as the precise
    the degrees of freedom, so long as they are orthogonal. For example, one can
    employ first-order (linear) interpolation around phonon displacements to calculate
    a conventional Raman spectrum. One can achieve identical results -- often with fewer
    calculations -- by using first-order interpolations around atomic displacements.

    This model's key assumption is that each degree of freedom in a system modulates
    the polarizability **independently**.

    Parameters
    ----------
    ref_structure
    equilibrium_polarizability
        2D array with shape (3,3) giving polarizability of system at equilibrium. This
        would usually correspond to the minimum energy structure.

    """

    def __init__(
        self,
        ref_structure: ReferenceStructure,
        equilibrium_polarizability: NDArray[np.float64],
    ) -> None:
        verify_ndarray_shape(
            "equilibrium_polarizability", equilibrium_polarizability, (3, 3)
        )
        self._ref_structure = ref_structure
        self._equilibrium_polarizability = equilibrium_polarizability
        self._cartesian_basis_vectors: list[NDArray[np.float64]] = []
        self._interpolations: list[BSpline] = []
        self._mask: NDArray[np.bool] = np.array([], dtype="bool")

    def get_polarizability(
        self, cartesian_displacement: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        """Return an estimated polarizability for a given cartesian displacement.

        Parameters
        ----------
        cartesian_displacement
            2D array with shape (N,3) where N is the number of atoms

        Returns
        -------
        :
            2D array with shape (3,3)

        """
        delta_polarizability: NDArray[np.float64] = np.zeros((3, 3))
        for basis_vector, interpolation, mask in zip(
            self._cartesian_basis_vectors, self._interpolations, self._mask
        ):
            try:
                amplitude = np.dot(
                    basis_vector.flatten(), cartesian_displacement.flatten()
                )
            except AttributeError as exc:
                raise TypeError("cartesian_displacement is not an ndarray") from exc
            except ValueError as exc:
                raise ValueError(
                    "cartesian_displacement has incompatible length "
                    f"({len(cartesian_displacement)}!={len(basis_vector)})"
                ) from exc
            delta_polarizability += (1 - mask) * np.array(
                interpolation(amplitude), dtype="float64"
            )

        return delta_polarizability + self._equilibrium_polarizability

    def _get_dof(  # pylint: disable=too-many-locals
        self,
        parent_displacement: NDArray[np.float64],
        amplitudes: NDArray[np.float64],
        polarizabilities: NDArray[np.float64],
        include_equilibrium_polarizability: bool,
    ) -> tuple[
        list[NDArray[np.float64]], list[list[float]], list[list[NDArray[np.float64]]]
    ]:
        """Calculate and return basis vectors and interpolation points for DOF(s).

        Parameters
        ----------
        parent_displacement
            Displacement of the parent DOF.
        amplitudes
            Amplitudes (of the parent DOF).
        polarizabilities
            Polarizabilities (of the parent DOF).

        Returns
        -------
        :
            3-tuple of the form (basis vectors, interpolation_xs, interpolation_ys)
        """
        # Check that the parent displacement is orthogonal to existing basis vectors
        parent_cartesian_basis_vector = self._ref_structure.get_cartesian_displacement(
            parent_displacement
        )
        result = is_orthogonal_to_all(
            parent_cartesian_basis_vector, self._cartesian_basis_vectors
        )
        if result != -1:
            raise InvalidDOFException(
                f"new dof is not orthogonal with existing dof (index={result})"
            )

        displacements_and_transformations = (
            self._ref_structure.get_equivalent_displacements(parent_displacement)
        )

        basis_vectors: list[NDArray[np.float64]] = []
        interpolation_xs: list[list[float]] = []
        interpolation_ys: list[list[NDArray[np.float64]]] = []
        for dof_dictionary in displacements_and_transformations:
            child_displacement = dof_dictionary["displacements"][0]

            interpolation_x: list[float] = []
            interpolation_y: list[NDArray[np.float64]] = []
            if include_equilibrium_polarizability:
                interpolation_x.append(0.0)
                interpolation_y.append(np.zeros((3, 3)))

            for collinear_displacement, transformation in zip(
                dof_dictionary["displacements"], dof_dictionary["transformations"]
            ):
                _index = np.unravel_index(
                    np.argmax(np.abs(child_displacement)), child_displacement.shape
                )
                multiplier = child_displacement[_index] / collinear_displacement[_index]

                for amplitude, polarizability in zip(amplitudes, polarizabilities):
                    interpolation_x.append(multiplier * amplitude)
                    rotation = transformation[0]
                    delta_polarizability = (
                        polarizability - self._equilibrium_polarizability
                    )

                    interpolation_y.append(
                        (np.linalg.inv(rotation) @ delta_polarizability @ rotation)
                    )

            child_cartesian_basis_vector = (
                self._ref_structure.get_cartesian_displacement(child_displacement)
            )
            child_cartesian_basis_vector /= np.linalg.norm(child_cartesian_basis_vector)

            basis_vectors.append(child_cartesian_basis_vector)
            interpolation_xs.append(interpolation_x)
            interpolation_ys.append(interpolation_y)

        return (basis_vectors, interpolation_xs, interpolation_ys)

    def _construct_and_add_interpolations(
        self,
        basis_vectors_to_add: list[NDArray[np.float64]],
        interpolation_xs: list[list[float]],
        interpolation_ys: list[list[NDArray[np.float64]]],
        interpolation_order: int,
    ) -> None:
        """Construct  interpolations and add them to the model.

        Raises
        ------
        InvalidDOFException
        """
        interpolations_to_add: list[BSpline] = []
        for interpolation_x, interpolation_y in zip(interpolation_xs, interpolation_ys):

            # Duplicate amplitudes means too much data has been provided.
            duplicate = find_duplicates(interpolation_x)
            if duplicate is not None:
                raise InvalidDOFException(
                    f"due to symmetry, amplitude {duplicate} should not be specified"
                )

            if len(interpolation_x) <= interpolation_order:
                raise InvalidDOFException(
                    f"insufficient points ({len(interpolation_x)}) available for "
                    f"{interpolation_order}-order interpolation"
                )

            # Warn user if amplitudes don't span zero
            max_amplitude = np.max(interpolation_x)
            min_amplitude = np.min(interpolation_x)
            if np.isclose(max_amplitude, 0, atol=1e-3).all() or max_amplitude <= 0:
                warn(
                    "max amplitude <= 0, when usually it should be > 0",
                    DOFWarning,
                )
            if np.isclose(min_amplitude, 0, atol=1e-3).all() or min_amplitude >= 0:
                warn(
                    "min amplitude >= 0, when usually it should be < 0",
                    DOFWarning,
                )

            sort_indices = np.argsort(interpolation_x)
            try:
                interpolations_to_add.append(
                    make_interp_spline(
                        x=np.array(interpolation_x)[sort_indices],
                        y=np.array(interpolation_y)[sort_indices],
                        k=interpolation_order,
                        bc_type=None,
                    )
                )
            except ValueError as exc:
                if "non-negative k" in str(exc):
                    raise ValueError(
                        f"invalid interpolation_order: {interpolation_order} < 1"
                    ) from exc
                raise exc
            except TypeError as exc:
                raise get_type_error(
                    "interpolation_order", interpolation_order, "int"
                ) from exc

        self._cartesian_basis_vectors += basis_vectors_to_add
        self._interpolations += interpolations_to_add
        # FALSE -> not masking, TRUE -> masking
        self._mask = np.append(self._mask, [False] * len(basis_vectors_to_add))

    def add_dof(  # pylint: disable=too-many-arguments
        self,
        displacement: NDArray[np.float64],
        amplitudes: NDArray[np.float64],
        polarizabilities: NDArray[np.float64],
        interpolation_order: int,
        include_equilibrium_polarizability: bool = True,
    ) -> None:
        """Add a degree of freedom (DOF).

        Specification of a DOF requires a displacement (how the atoms move) alongside
        displacement amplitudes and corresponding known polarizabilities for each
        amplitude. Alongside the DOF specified, all DOFs related by the system's
        symmetry will be added as well. The interpolation order can be specified,
        though one must ensure that sufficient data is available.

        Parameters
        ----------
        displacement
            2D array with shape (N,3) where N is the number of atoms. Units
            are arbitrary. Must be orthogonal to all previously added DOFs.
        amplitudes
            1D array of length L containing amplitudes in angstroms. Duplicate
            amplitudes are not allowed, including symmetrically equivalent
            amplitudes.
        polarizabilities
            3D array with shape (L,3,3) containing known polarizabilities for
            each amplitude.
        interpolation_order
            Must be less than the number of total number of amplitudes after
            symmetry considerations.
        include_equilibrium_polarizability
            If False, the equilibrium polarizability at 0.0 amplitude will not be used
            in the interpolation.

        Raises
        ------
        InvalidDOFException
            Provided degree of freedom was invalid.

        """
        try:
            parent_displacement = displacement / np.linalg.norm(displacement * 10.0)
        except TypeError as exc:
            raise TypeError("displacement is not an ndarray") from exc
        verify_ndarray_shape("amplitudes", amplitudes, (None,))
        verify_ndarray_shape(
            "polarizabilities", polarizabilities, (len(amplitudes), 3, 3)
        )

        # Get information needed for DOF
        basis_vectors_to_add, interpolation_xs, interpolation_ys = self._get_dof(
            parent_displacement,
            amplitudes,
            polarizabilities,
            include_equilibrium_polarizability,
        )

        # Then append the DOF.
        self._construct_and_add_interpolations(
            basis_vectors_to_add,
            interpolation_xs,
            interpolation_ys,
            interpolation_order,
        )

    def add_dof_from_files(
        self,
        filepaths: str | Path | list[str] | list[Path],
        file_format: str,
        interpolation_order: int,
    ) -> None:
        """Add a degree of freedom (DOF) from file(s).

        Required displacements, amplitudes, and polarizabilities are automatically
        determined from provided files. See "add_dof" for restrictions on these
        parameters.

        Parameters
        ----------
        filepaths
        file_format
            supports: "outcar"

        Raises
        ------
        FileNotFoundError
            File could not be found.
        InvalidDOFException
            DOF assembled from supplied files was invalid (see get_dof)

        """
        displacements, amplitudes, polarizabilities = self._read_dof(
            filepaths, file_format
        )

        self.add_dof(
            displacements[0],
            amplitudes,
            polarizabilities,
            interpolation_order,
        )

    def _read_dof(
        self, filepaths: str | Path | list[str] | list[Path], file_format: str
    ) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
        """Read displacements, amplitudes, and polarizabilities from file(s).

        Returns
        -------
        :
            3-tuple with the form (displacements, polarizabilities, basis vector)

        Raises
        ------
        FileNotFoundError
            File could not be found.
        InvalidDOFException
            DOF assembled from supplied files was invalid (see get_dof)
        """
        displacements = []
        polarizabilities = []
        filepaths = pathify_as_list(filepaths)
        for filepath in filepaths:
            fractional_positions, polarizability = io.read_positions_and_polarizability(
                filepath, file_format
            )
            try:
                displacement = calculate_displacement(
                    fractional_positions,
                    self._ref_structure.get_fractional_positions(),
                )
            except ValueError as exc:
                raise InvalidDOFException(f"incompatible outcar: {filepath}") from exc
            displacements.append(displacement)
            polarizabilities.append(polarizability)
        result = is_collinear_with_all(displacements[0], displacements)
        if result != -1:
            raise InvalidDOFException(
                f"displacement (file-index={result}) is not collinear"
            )
        cartesian_basis_vector = self._ref_structure.get_cartesian_displacement(
            displacements[0]
        )
        cartesian_basis_vector /= np.linalg.norm(cartesian_basis_vector)

        # Calculate amplitudes
        amplitudes = []
        for displacement in displacements:
            cartesian_displacement = self._ref_structure.get_cartesian_displacement(
                displacement
            )
            amplitudes.append(
                get_amplitude(cartesian_basis_vector, cartesian_displacement)
            )
        return (
            np.array(displacements),
            np.array(amplitudes),
            np.array(polarizabilities),
        )

    def get_mask(self) -> NDArray[np.bool]:
        """Return mask."""
        return self._mask

    def set_mask(self, mask: NDArray[np.bool]) -> None:
        """Set mask.

        ..warning:: To avoid unintentional use of masked models, we discourage masking
                    in-place. Instead, consider using `get masked_model`.

        Parameters
        ----------
        mask
            1D array of size (N,) where N is the number of specified degrees
            of freedom (DOFs). If an element is False, its corresponding DOF will be
            "masked" and therefore excluded from polarizability calculations.
        """
        verify_ndarray_shape("mask", mask, self._mask.shape)
        self._mask = mask

    def get_masked_model(self, dof_indexes_to_mask: list[int]) -> InterpolationModel:
        """Return new model with certain degrees of freedom deactivated.

        Model masking allows for the calculation of partial Raman spectra in which only
        certain degrees of freedom are considered.
        """
        result = copy.deepcopy(self)
        new_mask = result.get_mask()
        new_mask[:] = False
        new_mask[dof_indexes_to_mask] = True
        result.set_mask(new_mask)
        return result

    def unmask(self) -> None:
        """Clear mask, activating all specified DOFs."""
        self._mask[:] = False

    def __repr__(self) -> str:
        """Return string representation."""
        total_dofs = 3 * len(self._ref_structure.get_fractional_positions())
        specified_dofs = len(self._cartesian_basis_vectors)
        core = f"{specified_dofs}/{total_dofs}"
        if specified_dofs == total_dofs:
            core = AnsiColors.OK_GREEN + core + AnsiColors.END
        elif 1 <= specified_dofs < total_dofs:
            core = AnsiColors.WARNING_YELLOW + core + AnsiColors.END
        else:
            core = AnsiColors.ERROR_RED + core + AnsiColors.END

        result = f"InterpolationModel with {core} degrees of freedom specified."

        num_masked = np.sum(self._mask)
        if num_masked > 0:
            num_arts = len(self._cartesian_basis_vectors)
            msg = f"ATTENTION: {num_masked}/{num_arts} degrees of freedom are masked."
            result += f"\n {AnsiColors.WARNING_YELLOW} {msg} {AnsiColors.END}"

        return result
