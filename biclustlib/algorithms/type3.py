"""
    SeCCA: A Python library of privacy-preserved biclustering algorithm (Cheng and Church) with Homomorphic Encryption

    Copyright (C) 2022  Shokofeh VahidianSadegh

    This file is part of SeCCA.

"""

from ._base import BaseBiclusteringAlgorithm
from ..models import Bicluster, Biclustering
from sklearn.utils.validation import check_array
from Pyfhel import Pyfhel, PyCtxt
from scipy import stats

import numpy as np
import bottleneck as bn
import random
import math
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import time
import threading


class SecuredChengChurchAlgorithmType3(BaseBiclusteringAlgorithm):
    """Secured Cheng and Church's Algorithm (SeCCA Type 3)

    SeCCA searches for maximal submatrices with a Mean Squared Residue value below a pre-defined threshold
        by Homomorphic Encryption operations

    Parameters
    ----------
    num_biclusters : int, default: 5
        Number of biclusters to be found.

    msr_threshold : float or str, default: 'estimate'
        Maximum mean squared residue accepted (delta parameter in the original paper).
        If 'estimate', the algorithm will calculate this threshold as:
        (((max(data) - min(data)) ** 2) / 12) * 0.005.

    multiple_node_deletion_threshold : float, default: 1.2
        Scaling factor to remove multiple rows or columns (alpha parameter in the original paper).

    data_min_cols : int, default: 100
        Minimum number of dataset columns required to perform multiple column deletion.
    """

    def __init__(self, num_biclusters=5, msr_threshold= 300, multiple_node_deletion_threshold=1.2,
                 data_min_cols=100):
        self.num_biclusters = num_biclusters
        self.msr_threshold = msr_threshold
        self.multiple_node_deletion_threshold = multiple_node_deletion_threshold
        self.data_min_cols = data_min_cols

    def run(self, data):
        """Compute biclustering.

        Parameters
        ----------
        data : numpy.ndarray
        """
        print("SeCCA Step 3")
        # Creating empty Pyfhel object
        HE = Pyfhel()
        # Generating context
        ckks_params = {
            'scheme': 'CKKS',  # can also be 'ckks'
            'n': 2 ** 14,  # Polynomial modulus degree. For CKKS, n/2 values can be
            #  encoded in a single ciphertext.
            #  Typ. 2^D for D in [10, 16]
            'scale': 2 ** 30,  # All the encodings will use it for float->fixed point
            #  conversion: x_fix = round(x_float * scale)
            #  You can use this as default scale or use a different
            #  scale on each operation (set in HE.encryptFrac)
            'qi_sizes': [60, 30, 30, 30, 60]  # Number of bits of each prime in the chain.
            # Intermediate values should be  close to log2(scale)
            # for each operation, to have small rounding errors.
        }
        HE.contextGen(**ckks_params)  # Generate context for bfv scheme
        # Key Generation
        HE.keyGen()

        data = check_array(data, dtype=np.double, copy=True)
        self._validate_parameters()

        num_rows, num_cols = data.shape
        min_value = np.min(data)
        max_value = np.max(data)

        msr_thr = (((max_value - min_value) ** 2) / 12) * 0.005 if self.msr_threshold == 300 else self.msr_threshold

        biclusters = []
        t_enc = []
        t_dec = []
        for i in range(self.num_biclusters):
            print("Number of the Bicluster:{}".format(i))
            rows = np.ones(num_rows, dtype=np.bool)
            cols = np.ones(num_cols, dtype=np.bool)

            self._multiple_node_deletion(data, rows, cols, msr_thr, HE, t_enc, t_dec)
            self._single_node_deletion(data, rows, cols, msr_thr, HE, t_enc, t_dec)
            self._node_addition(data, rows, cols, HE, t_enc, t_dec)

            row_indices = np.nonzero(rows)[0]
            col_indices = np.nonzero(cols)[0]

            if len(row_indices) == 0 or len(col_indices) == 0:
                break

            # masking matrix values
            if i < self.num_biclusters - 1:
                bicluster_shape = (len(row_indices), len(col_indices))
                data[row_indices[:, np.newaxis], col_indices] = np.random.uniform(low=min_value, high=max_value,
                                                                                  size=bicluster_shape)

            biclusters.append(Bicluster(row_indices, col_indices))

        return Biclustering(biclusters)

    def _single_node_deletion(self, data, rows, cols, msr_thr, HE, t_enc, t_dec):
        """Performs the single row/column deletion step (this is a direct implementation of the Algorithm 1 described in
        the original paper)"""
        msr, row_msr, col_msr = self._calculate_msr(data, rows, cols, HE, t_enc, t_dec)

        while msr > msr_thr:
            self._single_deletion(data, rows, cols, row_msr, col_msr, HE)
            msr, row_msr, col_msr = self._calculate_msr(data, rows, cols, HE, t_enc, t_dec)

    def _single_deletion(self, data, rows, cols, row_msr, col_msr, HE):
        """Deletes a row or column from the bicluster being computed."""
        row_indices = np.nonzero(rows)[0]
        col_indices = np.nonzero(cols)[0]

        row_max_msr = np.argmax(row_msr)
        col_max_msr = np.argmax(col_msr)

        if row_msr[row_max_msr] >= col_msr[col_max_msr]:
            row2remove = row_indices[row_max_msr]
            rows[row2remove] = False
        else:
            col2remove = col_indices[col_max_msr]
            cols[col2remove] = False

    def _multiple_node_deletion(self, data, rows, cols, msr_thr, HE, t_enc, t_dec):
        """Performs the multiple row/column deletion step (this is a direct implementation of the Algorithm 2 described in
        the original paper)"""
        msr, row_msr, col_msr = self._calculate_msr(data, rows, cols, HE, t_enc, t_dec)

        stop = True if msr <= msr_thr else False

        while not stop:
            cols_old = np.copy(cols)
            rows_old = np.copy(rows)

            row_indices = np.nonzero(rows)[0]
            rows2remove = row_indices[np.where(row_msr > self.multiple_node_deletion_threshold * msr)]
            rows[rows2remove] = False

            if len(cols) >= self.data_min_cols:
                msr, row_msr, col_msr = self._calculate_msr(data, rows, cols, HE, t_enc, t_dec)
                col_indices = np.nonzero(cols)[0]
                cols2remove = col_indices[np.where(col_msr > self.multiple_node_deletion_threshold * msr)]
                cols[cols2remove] = False

            msr, row_msr, col_msr = self._calculate_msr(data, rows, cols, HE, t_enc, t_dec)

            # Tests if the new MSR value is smaller than the acceptable MSR threshold.
            # Tests if no rows and no columns were removed during this iteration.
            # If one of the conditions is true the loop must stop, otherwise it will become an infinite loop.
            if msr <= msr_thr or (np.all(rows == rows_old) and np.all(cols == cols_old)):
                stop = True

    def _node_addition(self, data, rows, cols, HE, t_enc, t_dec):
        """Performs the row/column addition step (this is a direct implementation of the Algorithm 3 described in
        the original paper)"""
        stop = False
        while not stop:
            cols_old = np.copy(cols)
            rows_old = np.copy(rows)

            msr, _, _ = self._calculate_msr(data, rows, cols, HE, t_enc, t_dec)
            col_msr = self._calculate_msr_col_addition(data, rows, cols, HE, t_enc, t_dec)
            cols2add = np.where(col_msr <= msr)[0]
            cols[cols2add] = True

            msr, _, _ = self._calculate_msr(data, rows, cols, HE, t_enc, t_dec)
            row_msr, row_inverse_msr = self._calculate_msr_row_addition(data, rows, cols, HE, t_enc, t_dec)
            rows2add = np.where(np.logical_or(row_msr <= msr, row_inverse_msr <= msr))[0]
            rows[rows2add] = True

            if np.all(rows == rows_old) and np.all(cols == cols_old):
                stop = True

    def _calculate_msr(self, data, rows, cols, HE, t_enc, t_dec):
        """Calculate the mean squared residues of the rows, of the columns and of the full data matrix."""
        sub_data = data[rows][:, cols]

        data_mean = np.mean(sub_data)
        row_means = np.mean(sub_data, axis=1)
        col_means = np.mean(sub_data, axis=0)

        residues = sub_data - row_means[:, np.newaxis] - col_means + data_mean
        squared_residues = residues * residues

        msr = np.mean(squared_residues)
        row_msr = np.mean(squared_residues, axis=1)
        col_msr = np.mean(squared_residues, axis=0)

        return msr, row_msr, col_msr

    def _calculate_msr_col_addition(self, data, rows, cols, HE, t_enc, t_dec):
        """Calculate the mean squared residues of the columns for the node addition step  by homomorphic encryption."""

        # SeCCA Type 3

        # Encrypting sub_data
        # 1. make sub_data a contiguous array in memory
        # 2. change 2d arrays into 1d
        # 3. Convert plaintext into ciphertext
        # 4. Reshape the array
        t_enc0 = time.perf_counter()
        sub_data = data[rows][:, cols]
        sub_data = np.ascontiguousarray(sub_data)
        enc_sub_data = sub_data.flatten()
        arr_sub_data = np.empty(len(enc_sub_data), dtype=PyCtxt)
        for i in np.arange(len(enc_sub_data)):
            arr_sub_data[i] = HE.encryptFrac(enc_sub_data[i])
        arr_sub_data = arr_sub_data.reshape(sub_data.shape)

        # Encrypting sub_data_rows
        # 1. make sub_data_rows a contiguous array in memory
        # 2. change 2d arrays into 1d
        # 3. Convert plaintext into ciphertext
        # 4. Reshape the array
        sub_data_rows = data[rows]
        sub_data_rows = np.ascontiguousarray(sub_data_rows)
        enc_sub_data_rows = sub_data_rows.flatten()
        arr_sub_data_rows = np.empty(len(enc_sub_data_rows), dtype=PyCtxt)
        for i in np.arange(len(enc_sub_data_rows)):
            arr_sub_data_rows[i] = HE.encryptFrac(enc_sub_data_rows[i])
        arr_sub_data_rows = arr_sub_data_rows.reshape(sub_data_rows.shape)

        # Encrypting data_mean
        enc_data_mean = np.sum(arr_sub_data) / len(enc_sub_data)

        # Encrypting and reshaping the row_means
        enc_row_means = np.mean(arr_sub_data, axis=1)
        enc_row_means = enc_row_means.reshape((sub_data.shape[0], 1))

        # Encrypting col_means
        enc_col_means = np.mean(arr_sub_data_rows, axis=0)

        # Encrypting col_residues
        enc_col_residues = arr_sub_data_rows - enc_row_means - enc_col_means + enc_data_mean

        # Encrypting ol_squared_residues
        enc_col_squared_residues = enc_col_residues ** 2

        # Encrypting col_msr
        enc_col_msr = np.mean(enc_col_squared_residues, axis=0)

        t_enc1 = time.perf_counter()
        t_enc.append(t_enc1 - t_enc0)
        print("Encryption Time: ", round(sum(t_enc), 5), "Seconds")

        # Decrypting msr_col
        t_dec0 = time.perf_counter()
        decrypted_msr_col = np.empty(len(enc_col_msr), dtype=PyCtxt)
        for i in np.arange(len(enc_col_msr)):
            decrypted_msr_col[i] = HE.decryptFrac(enc_col_msr[i])

        t_dec1 = time.perf_counter()
        t_dec.append(t_dec1 - t_dec0)
        print("Decryption time: ", round(sum(t_dec), 5), "Seconds")

        return decrypted_msr_col

    def _calculate_msr_row_addition(self, data, rows, cols, HE, t_enc, t_dec):
        """Calculate the mean squared residues of the rows and of the inverse of the rows for
        the node addition step."""
        sub_data = data[rows][:, cols]
        sub_data_cols = data[:, cols]

        data_mean = np.mean(sub_data)
        row_means = np.mean(sub_data_cols, axis=1)
        col_means = np.mean(sub_data, axis=0)

        row_residues = sub_data_cols - row_means[:, np.newaxis] - col_means + data_mean
        row_squared_residues = row_residues * row_residues
        row_msr = np.mean(row_squared_residues, axis=1)

        inverse_residues = -sub_data_cols + row_means[:, np.newaxis] - col_means + data_mean
        row_inverse_squared_residues = inverse_residues * inverse_residues
        row_inverse_msr = np.mean(row_inverse_squared_residues, axis=1)

        return row_msr, row_inverse_msr

    def _validate_parameters(self):
        if self.num_biclusters <= 0:
            raise ValueError("num_biclusters must be > 0, got {}".format(self.num_biclusters))

        if self.msr_threshold != 300 and self.msr_threshold < 0.0:
            raise ValueError("msr_threshold must be equal to 300 or a numeric value >= 0.0, got {}".format(
                self.msr_threshold))

        if self.multiple_node_deletion_threshold < 1.0:
            raise ValueError(
                "multiple_node_deletion_threshold must be >= 1.0, got {}".format(self.multiple_node_deletion_threshold))

        if self.data_min_cols < 100:
            raise ValueError("data_min_cols must be >= 100, got {}".format(self.data_min_cols))
