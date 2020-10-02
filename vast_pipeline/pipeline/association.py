import logging
import numpy as np
import pandas as pd
import dask.dataframe as dd
from psutil import cpu_count

from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.coordinates import Angle

from .loading import upload_associations, upload_sources
from .utils import (
    get_or_append_list, get_source_models, prep_skysrc_df
)
from vast_pipeline.models import Association
from vast_pipeline.utils.utils import StopWatch


logger = logging.getLogger(__name__)


def calc_de_ruiter(df):
    '''
    Calculates the unitless 'de Ruiter' radius of the
    association. Works on the 'temp_df' dataframe of the
    advanced association, where the two sources associated
    with each other have been merged into one row.
    '''
    ra_1 = df['ra_skyc1'].values
    ra_2 = df['ra_skyc2'].values

    # avoid wrapping issues
    ra_1[ra_1 > 270.] -= 180.
    ra_2[ra_2 > 270.] -= 180.
    ra_1[ra_1 < 90.] += 180.
    ra_2[ra_2 < 90.] += 180.

    ra_1 = np.deg2rad(ra_1)
    ra_2 = np.deg2rad(ra_2)

    ra_1_err = np.deg2rad(df['uncertainty_ew_skyc1'].values)
    ra_2_err = np.deg2rad(df['uncertainty_ew_skyc2'].values)

    dec_1 = np.deg2rad(df['dec_skyc1'].values)
    dec_2 = np.deg2rad(df['dec_skyc2'].values)

    dec_1_err = np.deg2rad(df['uncertainty_ns_skyc1'].values)
    dec_2_err = np.deg2rad(df['uncertainty_ns_skyc2'].values)

    dr1 = (ra_1 - ra_2) * (ra_1 - ra_2)
    dr1_1 = np.cos((dec_1 + dec_2) / 2.)
    dr1 *= dr1_1 * dr1_1
    dr1 /= ra_1_err * ra_1_err + ra_2_err * ra_2_err

    dr2 = (dec_1 - dec_2) * (dec_1 - dec_2)
    dr2 /= dec_1_err * dec_1_err + dec_2_err * dec_2_err

    dr = np.sqrt(dr1 + dr2)

    return dr


def one_to_many_basic(sources_df, skyc2_srcs):
    '''
    Finds and processes the one-to-many associations in the basic
    association. For each one-to-many association, the nearest
    associated source is assigned the original source id, where as
    the others are given new ids. The original source in skyc1 then
    is copied to the sources_df to provide the extra association for
    that source, i.e. it is forked.

    This is needed to be separate from the advanced version
    as the data products between the two are different.
    '''
    # select duplicated in 'source' field in skyc2_srcs, excluding -1
    duplicated_skyc2 = skyc2_srcs.loc[
        (skyc2_srcs['source'] != -1) &
        skyc2_srcs['source'].duplicated(keep=False),
        ['source', 'd2d']
    ]
    if duplicated_skyc2.empty:
        logger.debug('No one-to-many associations.')
        return sources_df, skyc2_srcs

    logger.info(
        'Detected #%i double matches, cleaning...',
        duplicated_skyc2.shape[0]
    )
    multi_srcs = duplicated_skyc2['source'].unique()

    # now we have the src values which are doubled.
    # make the nearest match have the "original" src id
    # give the other matched source a new src id
    # and make sure to copy the other previously
    # matched sources.
    for i, msrc in enumerate(multi_srcs):
        # 1) assign new source id and
        # get the sky2_sources with this source id and
        # get the minimum d2d index
        src_selection = duplicated_skyc2['source'] == msrc
        min_d2d_idx = duplicated_skyc2.loc[
            src_selection,
            'd2d'
        ].idxmin()
        # Get the indexes of the other skyc2 sources
        # which need to be changed
        idx_to_change = duplicated_skyc2.index.values[
            (duplicated_skyc2.index.values != min_d2d_idx) &
            src_selection
        ]
        # how many new source ids we need to make?
        num_to_add = idx_to_change.shape[0]
        # obtain the current start src elem
        start_src_id = sources_df['source'].values.max() + 1
        # Set the new index range
        new_src_ids = np.arange(
            start_src_id,
            start_src_id + num_to_add,
            dtype=int
        )
        # Set the new index values in the skyc2
        skyc2_srcs.loc[idx_to_change, 'source'] = new_src_ids

        # populate the 'related' field in skyc2_srcs
        # original source with duplicated
        orig_src = skyc2_srcs.at[min_d2d_idx, 'related']
        if isinstance(orig_src, list):
            skyc2_srcs.at[min_d2d_idx, 'related'] = (
                orig_src + new_src_ids.tolist()
            )
        else:
            skyc2_srcs.at[min_d2d_idx, 'related'] = new_src_ids.tolist()
        # other sources with original
        skyc2_srcs.loc[idx_to_change, 'related'] = skyc2_srcs.loc[
            idx_to_change,
            'related'
        ].apply(get_or_append_list, elem=msrc)

        # 2) Check for generate copies of previous crossmatches in
        # 'sources_df' and match them with new source id
        # e.g. clone f1 and f2 in https://tkp.readthedocs.io/en/
        # latest/devref/database/assoc.html#one-to-many-association
        # and assign them to f3
        for new_id in new_src_ids:
            # Get all the previous crossmatches to be cloned
            sources_to_copy = sources_df.loc[
                sources_df['source'] == msrc
            ].copy()
            # change source id with new one
            sources_to_copy['source'] = new_id
            # append copies to "sources_df"
            sources_df = sources_df.append(
                sources_to_copy,
                ignore_index=True
            )
    logger.info('Cleaned %i double matches.', i + 1)

    return sources_df, skyc2_srcs


def one_to_many_advanced(temp_srcs, sources_df, method):
    '''
    Finds and processes the one-to-many associations in the basic
    association. The same logic is applied as in
    'one_to_many_basic.

    This is needed to be separate from the basic version
    as the data products between the two are different.
    '''
    # use only these columns for easy debugging of the dataframe
    cols = [
        'index_old_skyc1', 'id_skyc1', 'source_skyc1', 'd2d_skyc1',
        'related_skyc1', 'index_old_skyc2', 'id_skyc2', 'source_skyc2',
        'd2d_skyc2', 'related_skyc2', 'dr'
    ]
    duplicated_skyc1 = temp_srcs.loc[
        temp_srcs['source_skyc1'].duplicated(keep=False), cols
    ]
    if duplicated_skyc1.empty:
        logger.debug('No one-to-many associations.')
        return temp_srcs, sources_df

    logger.debug(
        'Detected #%i one-to-many assocations, cleaning...',
        duplicated_skyc1.shape[0]
    )

    # Get the column to check for the minimum depending on the method
    # set the column names needed for filtering the 'to-many'
    # associations depending on the method (advanced or deruiter)
    dist_col = 'd2d_skyc2' if method == 'advanced' else 'dr'

    # go through the doubles and
    # 1. Keep the closest de ruiter as the primary id
    # 2. Increment a new source id for others
    # 3. Add a copy of the previously matched
    # source into sources.
    multi_srcs = duplicated_skyc1['source_skyc1'].unique()
    for i, msrc in enumerate(multi_srcs):
        # Make the selection
        src_selection = duplicated_skyc1['source_skyc1'] == msrc
        # Get the min d2d or dr idx
        min_dist_idx = duplicated_skyc1.loc[src_selection, dist_col].idxmin()
        # Select the others
        idx_to_change = duplicated_skyc1.index.values[
            (duplicated_skyc1.index.values != min_dist_idx) &
            src_selection
        ]
        # how many new source ids we need to make?
        num_to_add = idx_to_change.shape[0]
        # define a start src id for new forks
        start_src_id = sources_df['source'].values.max() + 1
        # Define new source ids
        new_src_ids = np.arange(
            start_src_id,
            start_src_id + num_to_add,
            dtype=int
        )
        # Apply the change to the temp sources
        temp_srcs.loc[idx_to_change, 'source_skyc1'] = new_src_ids
        # populate the 'related' field for skyc1
        # original source with duplicated
        orig_src = temp_srcs.at[min_dist_idx, 'related_skyc1']
        if isinstance(orig_src, list):
            temp_srcs.at[min_dist_idx, 'related_skyc1'] = (
                orig_src + new_src_ids.tolist()
            )
        else:
            temp_srcs.at[min_dist_idx, 'related_skyc1'] = new_src_ids.tolist()
        # other sources with original
        temp_srcs.loc[idx_to_change, 'related_skyc1'] = temp_srcs.loc[
            idx_to_change,
            'related_skyc1'
        ].apply(get_or_append_list, elem=msrc)

        # Check for generate copies of previous crossmatches and copy
        # the past source rows ready to append
        for new_id in new_src_ids:
            sources_to_copy = sources_df[
                sources_df['source'] == msrc
            ].copy()
            # change source id with new one
            sources_to_copy['source'] = new_id
            # append copies of skyc1 to source_df
            sources_df = sources_df.append(
                sources_to_copy,
                ignore_index=True
            )

    return temp_srcs, sources_df


def many_to_many_advanced(temp_srcs, method):
    '''
    Finds and processes the many-to-many associations in the advanced
    association. We do not want to build many-to-many associations as
    this will make the database get very large (see TraP documentation).
    The skyc2 sources which are listed more than once are found, and of
    these, those which have a skyc1 source association which is also
    listed twice in the associations are selected. The closest (by
    limit or de Ruiter radius, depending on the method) is kept where
    as the other associations are dropped.

    This follows the same logic used by the TraP (see TraP documentation).
    '''
    # Select those where the extracted source is listed more than once
    # (e.g. index_old_skyc2 duplicated values) and of these get those that
    # have a source id that is listed more than once (e.g. source_skyc1
    # duplicated values) in the temps_srcs df
    m_to_m = temp_srcs[(
        temp_srcs['index_old_skyc2'].duplicated(keep=False) &
        temp_srcs['source_skyc1'].duplicated(keep=False)
    )].copy()
    if m_to_m.empty:
        logger.debug('No many-to-many assocations.')
        return temp_srcs

    logger.debug(
        'Detected #%i many-to-many assocations, cleaning...',
        m_to_m.shape[0]
    )

    dist_col = 'd2d_skyc2' if method == 'advanced' else 'dr'
    min_col = 'min_' + dist_col

    # get the minimum de ruiter value for each extracted source
    m_to_m[min_col] = (
        m_to_m.groupby('index_old_skyc2')[dist_col]
        .transform('min')
    )
    # get the ids of those crossmatches that are larger than the minimum
    m_to_m_to_drop = m_to_m[m_to_m[dist_col] != m_to_m[min_col]].index.values
    # and drop these from the temp_srcs
    temp_srcs = temp_srcs.drop(m_to_m_to_drop)

    return temp_srcs


def many_to_one_advanced(temp_srcs):
    '''
    Finds and processes the many-to-one associations in the advanced
    association.
    '''
    # use only these columns for easy debugging of the dataframe
    cols = [
        'index_old_skyc1', 'id_skyc1', 'source_skyc1', 'd2d_skyc1',
        'related_skyc1', 'index_old_skyc2', 'id_skyc2', 'source_skyc2',
        'd2d_skyc2', 'related_skyc2', 'dr'
    ]

    duplicated_skyc2 = temp_srcs.loc[
            temp_srcs['index_old_skyc2'].duplicated(keep=False),
            cols
    ]
    if duplicated_skyc2.empty:
        logger.debug('No many-to-one associations.')
        return temp_srcs

    logger.debug(
        'Detected #%i many-to-one associations',
        duplicated_skyc2.shape[0]
    )

    multi_srcs = duplicated_skyc2['index_old_skyc2'].unique()
    for i, msrc in enumerate(multi_srcs):
        # Make the selection
        src_sel_idx = duplicated_skyc2.loc[
            duplicated_skyc2['index_old_skyc2'] == msrc
        ].index
        # populate the 'related' field for skyc1
        for idx in src_sel_idx:
            related = temp_srcs.loc[
                src_sel_idx.drop(idx), 'source_skyc1'
            ].tolist()
            elem = temp_srcs.at[idx, 'related_skyc1']
            if isinstance(elem, list):
                temp_srcs.at[idx, 'related_skyc1'] = (
                    elem + related
                )
            else:
                temp_srcs.at[idx, 'related_skyc1'] = related

    return temp_srcs


def basic_association(
        sources_df, skyc1_srcs, skyc1, skyc2_srcs, skyc2, limit
    ):
    '''
    The loop for basic source association that uses the astropy
    'match_to_catalog_sky' function (i.e. only the nearest match between
    the catalogs). A direct on sky separation is used to define the association.
    '''
    # match the new sources to the base
    # idx gives the index of the closest match in the base for skyc2
    idx, d2d, d3d = skyc2.match_to_catalog_sky(skyc1)
    # acceptable selection
    sel = d2d <= limit

    # The good matches can be assinged the src id from base
    skyc2_srcs.loc[sel, 'source'] = skyc1_srcs.loc[idx[sel], 'source'].values
    # Need the d2d to make analysing doubles easier.
    skyc2_srcs.loc[sel, 'd2d'] = d2d[sel].arcsec

    # must check for double matches in the acceptable matches just made
    # this would mean that multiple sources in skyc2 have been matched
    #  to the same base source we want to keep closest match and move
    # the other match(es) back to having a -1 src id
    sources_df, skyc2_srcs = one_to_many_basic(sources_df, skyc2_srcs)

    logger.info('Updating sources catalogue with new sources...')
    # update the src numbers for those sources in skyc2 with no match
    # using the max current src as the start and incrementing by one
    start_elem = sources_df['source'].values.max() + 1
    nan_sel = (skyc2_srcs['source'] == -1).values
    skyc2_srcs.loc[nan_sel, 'source'] = (
        np.arange(
            start_elem,
            start_elem + skyc2_srcs.loc[nan_sel].shape[0],
            dtype=int
        )
    )

    # and skyc2 is now ready to be appended to new sources
    sources_df = sources_df.append(
        skyc2_srcs, ignore_index=True
    ).reset_index(drop=True)

    # update skyc1 and df for next association iteration
    # calculate average angles for skyc1
    skyc1_srcs = (
        skyc1_srcs.append(skyc2_srcs[nan_sel], ignore_index=True)
        .reset_index(drop=True)
    )

    return sources_df, skyc1_srcs


def advanced_association(
        method, sources_df, skyc1_srcs, skyc1,
        skyc2_srcs, skyc2, dr_limit, bw_max
    ):
    '''
    The loop for advanced source association that uses the astropy
    'search_around_sky' function (i.e. all matching sources are
    found). The BMAJ of the image * the user supplied beamwidth
    limit is the base distance for association. This is followed
    by calculating the 'de Ruiter' radius.
    '''
    # read the needed sources fields
    # Step 1: get matches within semimajor axis of image.
    idx_skyc1, idx_skyc2, d2d, d3d = skyc2.search_around_sky(
        skyc1, bw_max
    )
    # Step 2: Apply the beamwidth limit
    sel = d2d <= bw_max

    skyc2_srcs.loc[idx_skyc2[sel], 'd2d'] = d2d[sel].arcsec

    # Step 3: merge the candidates so the de ruiter can be calculated
    temp_skyc1_srcs = (
        skyc1_srcs.loc[idx_skyc1[sel]]
        .reset_index()
        .rename(columns={'index': 'index_old'})
    )
    temp_skyc2_srcs = (
        skyc2_srcs.loc[idx_skyc2[sel]]
        .reset_index()
        .rename(columns={'index': 'index_old'})
    )
    temp_srcs = temp_skyc1_srcs.merge(
        temp_skyc2_srcs,
        left_index=True,
        right_index=True,
        suffixes=('_skyc1', '_skyc2')
    )
    del temp_skyc1_srcs, temp_skyc2_srcs

    # Step 4: Calculate and perform De Ruiter radius cut
    if method == 'deruiter':
        temp_srcs['dr'] = calc_de_ruiter(temp_srcs)
        temp_srcs = temp_srcs[temp_srcs['dr'] <= dr_limit]
    else:
        temp_srcs['dr'] = 0.

    # Now have the 'good' matches
    # Step 5: Check for one-to-many, many-to-one and many-to-many
    # associations. First the many-to-many
    temp_srcs = many_to_many_advanced(temp_srcs, method)

    # Next one-to-many
    # Get the sources which are doubled
    temp_srcs, sources_df = one_to_many_advanced(
        temp_srcs, sources_df, method
    )

    # Finally many-to-one associations, the opposite of above but we
    # don't have to create new ids for these so it's much simpler in fact
    # we don't need to do anything but lets get the number for debugging.
    temp_srcs = many_to_one_advanced(temp_srcs)

    # Now everything in place to append
    # First the skyc2 sources with a match.
    # This is created from the temp_srcs df.
    # This will take care of the extra skyc2 sources needed.
    skyc2_srcs_toappend = skyc2_srcs.loc[
        temp_srcs['index_old_skyc2'].values
    ].reset_index(drop=True)
    skyc2_srcs_toappend['source'] = temp_srcs['source_skyc1'].values
    skyc2_srcs_toappend['related'] = temp_srcs['related_skyc1'].values
    skyc2_srcs_toappend['dr'] = temp_srcs['dr'].values

    # and get the skyc2 sources with no match
    logger.info(
        'Updating sources catalogue with new sources...'
    )
    new_sources = skyc2_srcs.loc[
        skyc2_srcs.index.difference(
            temp_srcs['index_old_skyc2'].values
        )
    ].reset_index(drop=True)
    # update the src numbers for those sources in skyc2 with no match
    # using the max current src as the start and incrementing by one
    start_elem = sources_df['source'].values.max() + 1
    new_sources['source'] = np.arange(
        start_elem,
        start_elem + new_sources.shape[0],
        dtype=int
    )
    skyc2_srcs_toappend = skyc2_srcs_toappend.append(
        new_sources, ignore_index=True
    )

    # and skyc2 is now ready to be appended to source_df
    sources_df = sources_df.append(
        skyc2_srcs_toappend, ignore_index=True
    ).reset_index(drop=True)

    # update skyc1 and df for next association iteration
    # calculate average angles for skyc1
    skyc1_srcs = (
        skyc1_srcs.append(new_sources, ignore_index=True)
        .reset_index(drop=True)
    )

    # also need to append any related sources that created a new
    # source, we can use the skyc2_srcs_toappend to get these
    skyc1_srcs = skyc1_srcs.append(
        skyc2_srcs_toappend.loc[
            ~skyc2_srcs_toappend.source.isin(skyc1_srcs.source)
        ]
    )

    return sources_df, skyc1_srcs


def association(images_df, limit, dr_limit, bw_limit,
    duplicate_limit, config):
    '''
    The main association function that does the common tasks between basic
    and advanced modes.
    '''
    timer = StopWatch()

    if 'skyreg_group' in images_df.columns:
        skyreg_group = images_df['skyreg_group'].iloc[0]
        skyreg_tag = " (sky region group %s)" % skyreg_group
    else:
        skyreg_tag = ""

    method = config.ASSOCIATION_METHOD

    logger.info('Starting association%s.', skyreg_tag)
    logger.info('Association mode selected: %s.', method)

    # if isinstance(images, pd.DataFrame):
    #     images = images['image'].to_list()
    unique_epochs = images_df.sort_values(by='epoch')['epoch'].unique()

    first_images = images_df.loc[
        images_df['epoch'] == unique_epochs[0]
    ]['image'].to_list()

    # initialise sky source dataframe
    skyc1_srcs = prep_skysrc_df(
        first_images,
        config.FLUX_PERC_ERROR,
        duplicate_limit,
        ini_df=True
    )
    skyc1_srcs['epoch'] = unique_epochs[0]
    # create base catalogue
    skyc1 = SkyCoord(
        ra=skyc1_srcs['ra'].values * u.degree,
        dec=skyc1_srcs['dec'].values * u.degree
    )
    # initialise the sources dataframe using first image as base
    sources_df = skyc1_srcs.copy()

    for it, epoch in enumerate(unique_epochs[1:]):
        logger.info('Association iteration: #%i%s', it + 1, skyreg_tag)
        # load skyc2 source measurements and create SkyCoord
        images = images_df.loc[
            images_df['epoch'] == epoch
        ]['image'].to_list()
        max_beam_maj = (
            images_df.loc[images_df['epoch'] == epoch, 'image']
            .apply(lambda x: x.beam_bmaj)
            .max()
        )
        skyc2_srcs = prep_skysrc_df(
            images,
            config.FLUX_PERC_ERROR,
            duplicate_limit
        )
        skyc2_srcs['epoch'] = epoch
        skyc2 = SkyCoord(
            ra=skyc2_srcs['ra'].values * u.degree,
            dec=skyc2_srcs['dec'].values * u.degree
        )

        if method == 'basic':
            sources_df, skyc1_srcs = basic_association(
                sources_df,
                skyc1_srcs,
                skyc1,
                skyc2_srcs,
                skyc2,
                limit,
            )

        elif method in ['advanced', 'deruiter']:
            if method == 'deruiter':
                bw_max = Angle(
                    bw_limit * (max_beam_maj * 3600. / 2.) * u.arcsec
                )
            else:
                bw_max = limit
            sources_df, skyc1_srcs = advanced_association(
                method,
                sources_df,
                skyc1_srcs,
                skyc1,
                skyc2_srcs,
                skyc2,
                dr_limit,
                bw_max
            )

        else:
            raise Exception('association method not implemented!')

        logger.info(
            'Calculating weighted average RA and Dec for sources%s...',
            skyreg_tag
        )

        # account for RA wrapping
        ra_wrap_mask = sources_df.ra <= 0.1
        sources_df['ra_wrap'] = sources_df.ra.values
        sources_df.at[
            ra_wrap_mask, 'ra_wrap'
        ] = sources_df[ra_wrap_mask].ra.values + 360.

        sources_df['interim_ew'] = (
            sources_df['ra_wrap'].values * sources_df['weight_ew'].values
        )
        sources_df['interim_ns'] = (
            sources_df['dec'].values * sources_df['weight_ns'].values
        )

        sources_df = sources_df.drop(['ra_wrap'], axis=1)

        tmp_srcs_df = (
            sources_df.loc[sources_df['source'] != -1, [
                'ra', 'dec', 'uncertainty_ew', 'uncertainty_ns',
                'source', 'interim_ew', 'interim_ns', 'weight_ew',
                'weight_ns'
            ]]
            .groupby('source')
        )

        stats = StopWatch()

        wm_ra = tmp_srcs_df['interim_ew'].sum() / tmp_srcs_df['weight_ew'].sum()
        wm_uncertainty_ew = 1. / np.sqrt(tmp_srcs_df['weight_ew'].sum())

        wm_dec = tmp_srcs_df['interim_ns'].sum() / tmp_srcs_df['weight_ns'].sum()
        wm_uncertainty_ns = 1. / np.sqrt(tmp_srcs_df['weight_ns'].sum())

        weighted_df = (
            pd.concat(
                [wm_ra, wm_uncertainty_ew, wm_dec, wm_uncertainty_ns],
                axis=1,
                sort=False
            )
            .reset_index()
            .rename(
                columns={
                    0: 'ra',
                    'weight_ew': 'uncertainty_ew',
                    1: 'dec',
                    'weight_ns': 'uncertainty_ns'
            })
        )

        # correct the RA wrapping
        ra_wrap_mask = weighted_df.ra >= 360.
        weighted_df.at[
            ra_wrap_mask, 'ra'
        ] = weighted_df[ra_wrap_mask].ra.values - 360.

        logger.debug('Groupby concat time %f', stats.reset())

        logger.info(
            'Finalising base sources catalogue ready for next iteration%s...',
            skyreg_tag
        )
        # merge the weighted ra and dec and replace the values
        skyc1_srcs = skyc1_srcs.merge(
            weighted_df,
            on='source',
            how='left',
            suffixes=('', '_skyc2')
        )
        del tmp_srcs_df
        del weighted_df
        skyc1_srcs['ra'] = skyc1_srcs['ra_skyc2']
        skyc1_srcs['dec'] = skyc1_srcs['dec_skyc2']
        skyc1_srcs['uncertainty_ew'] = skyc1_srcs['uncertainty_ew_skyc2']
        skyc1_srcs['uncertainty_ns'] = skyc1_srcs['uncertainty_ns_skyc2']
        skyc1_srcs = skyc1_srcs.drop(
            [
                'ra_skyc2',
                'dec_skyc2',
                'uncertainty_ew_skyc2',
                'uncertainty_ns_skyc2'
            ], axis=1
        )

        #generate new sky coord ready for next iteration
        skyc1 = SkyCoord(
            ra=skyc1_srcs['ra'] * u.degree,
            dec=skyc1_srcs['dec'] * u.degree
        )
        logger.info(
            'Association iteration #%i complete%s.', it + 1, skyreg_tag
        )

    # End of iteration over images, ra and dec columns are actually the
    # average over each iteration so remove ave ra and ave dec used for
    # calculation and use ra_source and dec_source columns
    sources_df = (
        sources_df.drop(['ra', 'dec'], axis=1)
        .rename(columns={'ra_source':'ra', 'dec_source':'dec'})
    )

    logger.info(
        'Total association time: %.2f seconds%s.',
        timer.reset_init(),
        skyreg_tag
    )
    return sources_df


def _correct_parallel_source_ids(
    df: pd.DataFrame, correction: int
) -> pd.DataFrame:
    """
    This function is to correct the source ids after the combination of
    the associaiton dataframes produced by parallel association - as source
    ids will be duplicated if left.

    Parameters
    ----------
    df : pd.DataFrame
        Holds the measurements associated into sources. The output of of the
        association step (sources_df).
    correction : int
        The value to add to the source ids.

    Returns
    -------
    df : pd.DataFrame
        The input df with correct source ids.
    """
    df.loc[:, 'source'] = df['source'].values + correction
    related_mask = ~(df['related'].isna())

    new_relations = df.loc[
        related_mask, 'related'
    ].explode() + correction

    df.loc[
        df[related_mask].index.values, 'related'
    ] = new_relations.groupby(level=0).apply(
        lambda x: x.values.tolist()
    )

    return df


def parallel_association(
    images_df: pd.DataFrame,
    limit: Angle,
    dr_limit: float,
    bw_limit: float,
    duplicate_limit: Angle,
    config,
    n_skyregion_groups: int
) -> pd.DataFrame:
    """
    Launches association on different sky region groups in parallel using Dask.

    Parameters
    ----------
    images_df : pd.DataFrame
        Holds the images that are being processed. Also contains what sky
        region group the image belongs to.
    limit: Angle
        The association radius limit.
    dr_limit : float
        The de Ruiter radius limit.
    bw_limit : float
        The beamwidth limit.
    duplicate_limit: Angle
        The duplicate radius detection limit.
    config : module
        The pipeline config settings.
    n_skyregion_groups: int
        The number of sky region groups.

    Returns
    -------
    results : pd.DataFrame
        The combined association results of the parallel association with
        corrected source ids.
    """
    logger.info(
        "Running parallel association for %i sky region groups.",
        n_skyregion_groups
    )

    timer = StopWatch()

    meta = {
        'id': 'i',
        'uncertainty_ew': 'f',
        'weight_ew': 'f',
        'uncertainty_ns': 'f',
        'weight_ns': 'f',
        'flux_int': 'f',
        'flux_int_err': 'f',
        'flux_peak': 'f',
        'flux_peak_err': 'f',
        'forced': '?',
        'compactness': 'f',
        'has_siblings': '?',
        'snr': 'f',
        'image': 'U',
        'datetime': 'datetime64[ns]',
        'source': 'i',
        'ra': 'f',
        'dec': 'f',
        'd2d': 'f',
        'dr': 'f',
        'related': 'O',
        'epoch': 'i',
        'interim_ew': 'f',
        'interim_ns': 'f',
    }

    n_cpu = cpu_count() - 1

    results = (
        dd.from_pandas(images_df, n_cpu)
        .groupby('skyreg_group')
        .apply(
            association,
            limit=limit,
            dr_limit=dr_limit,
            bw_limit=bw_limit,
            duplicate_limit=duplicate_limit,
            config=config,
            meta=meta
        ).compute(n_workers=n_cpu, scheduler='processes')
    )

    indexes = results.index.levels[0].values

    for i in indexes[1:]:
        max_id = results.loc[i - 1].source.max()
        corr_df = _correct_parallel_source_ids(
            results.loc[i].loc[:, ['source', 'related']],
            max_id
        )
        # I couldn't get the value set to work without a copy
        # warning without setting the multi-index first.
        corr_df.index = results.loc[(i, slice(None)), ].index
        results.loc[
            (i, slice(None)) , ['source', 'related']
        ] = corr_df

    results = results.reset_index(drop=True)

    logger.info(
        'Total parallel association time: %.2f seconds', timer.reset_init()
    )

    return results
