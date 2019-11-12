"""
Collect metrics.
"""
import logging

import numpy as np
import pandas as pd

from . import dependence
from ._utils import determine_signs, flip_components, sort_df, apply_sort


LGR = logging.getLogger(__name__)
RepLGR = logging.getLogger('REPORT')
RefLGR = logging.getLogger('REFERENCES')


def generate_metrics(data_cat, data_optcom, mixing, mask, tes, ref_img, mixing_z=None,
                     metrics=None, sort_by='kappa', ascending=False):
    """
    Fit TE-dependence and -independence models to components.

    Parameters
    ----------
    data_cat : (S x E x T) array_like
        Input data, where `S` is samples, `E` is echos, and `T` is time
    data_optcom : (S x T) array_like
        Optimally combined data
    mixing : (T x C) array_like
        Mixing matrix for converting input data to component space, where `C`
        is components and `T` is the same as in `data_cat`
    mask : img_like
        Mask
    tes : list
        List of echo times associated with `data_cat`, in milliseconds
    ref_img : str or img_like
        Reference image to dictate how outputs are saved to disk
    mixing_z : (T x C) array_like, optional
        Z-scored mixing matrix. Default: None
    metrics : list
        List of metrics to return
    sort_by : str
        Metric to sort component table by
    ascending : bool
        Whether to sort the table in ascending or descending order.
    out_dir : :obj:`str`, optional
        Output directory for generated files. Default is current working directory.

    Returns
    -------
    comptable : (C x X) :obj:`pandas.DataFrame`
        Component metric table. One row for each component, with a column for
        each metric. The index is the component number.
    mixing : :obj:`numpy.ndarray`
        Mixing matrix after sign flipping and sorting.
    """
    if metrics is None:
        metrics = []
    RepLGR.info('The following metrics were calculated: {}.'.format(', '.join(metrics)))

    if not (data_cat.shape[0] == data_optcom.shape[0] == mask.sum()):
        raise ValueError('First dimensions (number of samples) of data_cat ({0}), '
                         'data_optcom ({1}), and mask ({2}) do not '
                         'match'.format(data_cat.shape[0], data_optcom.shape[0],
                                        mask.shape[0]))
    elif data_cat.shape[1] != len(tes):
        raise ValueError('Second dimension of data_cat ({0}) does not match '
                         'number of echoes provided (tes; '
                         '{1})'.format(data_cat.shape[1], len(tes)))
    elif not (data_cat.shape[2] == data_optcom.shape[1] == mixing.shape[0]):
        raise ValueError('Number of volumes in data_cat ({0}), '
                         'data_optcom ({1}), and mixing ({2}) do not '
                         'match.'.format(data_cat.shape[2], data_optcom.shape[1], mixing.shape[0]))

    mixing = mixing.copy()
    n_components = mixing.shape[1]
    comptable = pd.DataFrame(index=np.arange(n_components, dtype=int))

    # Metric maps
    weights = dependence.calculate_weights(data_optcom, mixing_z)
    signs = determine_signs(weights, axis=0)
    weights, mixing = flip_components(weights, mixing, signs=signs)
    optcom_betas = dependence.calculate_betas(data_optcom, mixing)
    PSC = dependence.calculate_psc(data_optcom, optcom_betas)
    Z_maps = dependence.calculate_z_maps(weights)
    F_T2_maps, F_S0_maps = dependence.calculate_f_maps(mixing, data_cat, tes, Z_maps)
    (Z_clmaps, F_T2_clmaps, F_S0_clmaps,
     Br_T2_clmaps, Br_S0_clmaps) = dependence.spatial_cluster(
        F_T2_maps, F_S0_maps, Z_maps, optcom_betas, mask, ref_img, len(tes))

    # Dependence metrics
    comptable['kappa'], comptable['rho'] = dependence.calculate_dependence_metrics(
        F_T2_maps, F_S0_maps, Z_maps)

    # Generic metrics
    comptable['variance explained'] = dependence.calculate_varex(optcom_betas)

    comptable['normalized variance explained'] = dependence.calculate_varex_norm(weights)

    # Spatial metrics
    comptable['dice_FT2'] = dependence.compute_dice(Br_T2_clmaps, F_T2_clmaps, axis=0)

    comptable['dice_FS0'] = dependence.compute_dice(Br_S0_clmaps, F_S0_clmaps, axis=0)

    (comptable['signal-noise_t'],
        comptable['signal-noise_p']) = dependence.compute_signal_minus_noise_t(
        Z_maps, Z_clmaps, F_T2_maps)

    comptable['countnoise'] = dependence.compute_countnoise(Z_maps, Z_clmaps)

    comptable['countsigFT2'] = dependence.compute_countsignal(F_T2_clmaps)

    comptable['countsigFS0'] = dependence.compute_countsignal(F_S0_clmaps)

    comptable['d_table_score'] = dependence.generate_decision_table_score(
        comptable['kappa'], comptable['dice_FT2'],
        comptable['signal_minus_noise_t'], comptable['countnoise'],
        comptable['countsigFT2'])

    comptable, sort_idx = sort_df(comptable, by='kappa', ascending=ascending)
    mixing = apply_sort(mixing, sort_idx=sort_idx, axis=1)

    # Just calculate everything for now and only return the requested metrics
    comptable = comptable[metrics]
    return comptable, mixing