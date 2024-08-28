"""Generic IO routines.

Generic IO routines are somewhat inflexible but are necessary for certain
functionality. Users are strongly encouraged to use IO routines contained in the
code-specific subpackages. For example, IO for VASP POSCAR and OUTCAR files can be
accomplished using `ramannoodle.io.vasp.poscar` or :mod:`ramannoodle.io.vasp.outcar`
respectively.

"""

from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from ramannoodle.dynamics.phonon import Phonons

# from ramannoodle.dynamics.trajectory import Trajectory

from ramannoodle.structure.reference import ReferenceStructure
import ramannoodle.io.vasp as vasp_io

# These  map between file formats and appropriate IO functions.
_PHONON_READERS = {"outcar": vasp_io.outcar.read_phonons}
# _TRAJECTORY_READERS = {}
_POSITION_AND_POLARIZABILITY_READERS = {
    "outcar": vasp_io.outcar.read_positions_and_polarizability
}
_POSITION_READERS = {
    "outcar": vasp_io.outcar.read_positions,
    "poscar": vasp_io.poscar.read_positions,
}
_REFERENCE_STRUCTURE_READERS = {
    "outcar": vasp_io.outcar.read_ref_structure,
    "poscar": vasp_io.poscar.read_ref_structure,
}
_STRUCTURE_WRITERS = {"poscar": vasp_io.poscar.write_structure}
_TRAJECTORY_WRITERS = {"xdatcar": vasp_io.xdatcar.write_trajectory}


def read_phonons(filepath: str | Path, file_format: str) -> Phonons:
    """Read phonons from a file.

    Parameters
    ----------
    filepath
    file_format
        Supports: "outcar" (see :ref:`Supported formats`)

    Returns
    -------
    :

    Raises
    ------
    InvalidFileException
        File has unexpected format.
    FileNotFoundError
        File could not be found.
    """
    try:
        return _PHONON_READERS[file_format](filepath)
    except KeyError as exc:
        raise ValueError(f"unsupported format: {file_format}") from exc


# def read_trajectory(filepath: str | Path, file_format: str) -> Trajectory:
#     """Read molecular dynamics trajectory from a file.

#     Parameters
#     ----------
#     filepath
#     file_format
#         Supports: (none) (see :ref:`Supported formats`). To read a trajectory from an
#         XDATCAR, use :func:`.xdatcar.read_trajectory`.

#     Returns
#     -------
#     :

#     Raises
#     ------
#     InvalidFileException
#         File has unexpected format.
#     FileNotFoundError
#         File could not be found.
#     """
#     try:
#         return _TRAJECTORY_READERS[file_format](filepath)
#     except KeyError as exc:
#         if file_format == "xdatcar":
#             raise ValueError(
#                 "generic read_trajectory does not support xdatcar"
#             ) from exc
#         raise ValueError(f"unsupported format: {file_format}") from exc


def read_positions_and_polarizability(
    filepath: str | Path,
    file_format: str,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Read fractional positions and polarizability from a file.

    Parameters
    ----------
    filepath
    file_format
        Supports: "outcar" (see :ref:`Supported formats`)

    Returns
    -------
    :
        2-tuple, whose first element is the fractional positions, a 2D array with shape
        (N,3) where N is the number of atoms. The second element is the polarizability
        (unitless), a 2D array with shape (3,3).

    Raises
    ------
    InvalidFileException
        File has unexpected format.
    FileNotFoundError
        File could not be found.
    """
    try:
        return _POSITION_AND_POLARIZABILITY_READERS[file_format](filepath)
    except KeyError as exc:
        raise ValueError(f"unsupported format: {file_format}") from exc


def read_positions(
    filepath: str | Path,
    file_format: str,
) -> NDArray[np.float64]:
    """Read fractional positions from a file.

    Parameters
    ----------
    filepath
    file_format
        Supports: "outcar", "poscar" (see :ref:`Supported formats`).

    Returns
    -------
    :
        Unitless | 2D array with shape (N,3) where N is the number of atoms.

    Raises
    ------
    InvalidFileException
        File has unexpected format.
    FileNotFoundError
        File could not be found.
    """
    try:
        return _POSITION_READERS[file_format](filepath)
    except KeyError as exc:
        raise ValueError(f"unsupported format: {file_format}") from exc


def read_ref_structure(filepath: str | Path, file_format: str) -> ReferenceStructure:
    """Read reference structure from a file.

    Parameters
    ----------
    filepath
    file_format
        Supports: "outcar", "poscar" (see :ref:`Supported formats`).

    Returns
    -------
    StructuralSymmetry

    Raises
    ------
    InvalidFileException
        File has unexpected format.
    FileNotFoundError
        File could not be found.
    """
    try:
        return _REFERENCE_STRUCTURE_READERS[file_format](filepath)
    except KeyError as exc:
        raise ValueError(f"unsupported format: {file_format}") from exc


def write_structure(  # pylint: disable=too-many-arguments
    lattice: NDArray[np.float64],
    atomic_numbers: list[int],
    positions: NDArray[np.float64],
    filepath: str | Path,
    file_format: str,
    overwrite: bool = False,
) -> None:
    """Write structure to file.

    Parameters
    ----------
    lattice
        Å | 2D array with shape (3,3).
    atomic_numbers
        1D list of length N where N is the number of atoms.
    positions
        Unitless | 2D array with shape (N,3).
    filepath
    file_format
        Supports: "poscar" (see :ref:`Supported formats`).
    overwrite
        overwrite the file if it exists.

    Raises
    ------
    FileExistsError - File exists and ``overwrite = False``.
    """
    try:
        _STRUCTURE_WRITERS[file_format](
            lattice=lattice,
            atomic_numbers=atomic_numbers,
            positions=positions,
            filepath=filepath,
            overwrite=overwrite,
        )
    except KeyError as exc:
        raise ValueError(f"unsupported format: {file_format}") from exc


def write_trajectory(  # pylint: disable=too-many-arguments
    lattice: NDArray[np.float64],
    atomic_numbers: list[int],
    positions_ts: NDArray[np.float64],
    filepath: str | Path,
    file_format: str,
    overwrite: bool = False,
) -> None:
    """Write trajectory to file.

    Parameters
    ----------
    lattice
        Å | 2D array with shape (3,3).
    atomic_numbers
        1D list of length N where N is the number of atoms.
    positions_ts
        Unitless | 3D array with shape (S,N,3) where S is the number of configurations.
    filepath
    file_format
        Supports: "poscar" (see :ref:`Supported formats`).
    overwrite
        overwrite the file if it exists.

    Raises
    ------
    FileExistsError - File exists and ``overwrite = False``.
    """
    try:
        _TRAJECTORY_WRITERS[file_format](
            lattice=lattice,
            atomic_numbers=atomic_numbers,
            positions_ts=positions_ts,
            filepath=filepath,
            overwrite=overwrite,
        )
    except KeyError as exc:
        raise ValueError(f"unsupported format: {file_format}") from exc
