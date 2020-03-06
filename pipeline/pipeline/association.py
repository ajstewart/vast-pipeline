import logging
import numpy as np
import pandas as pd

from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.coordinates import Angle

from ..models import Association, Source
from ..utils.utils import deg2hms, deg2dms


logger = logging.getLogger(__name__)


def get_eta_metric(row, df, peak=False):
    if row['Nsrc'] == 1:
        return 0.
    suffix = 'peak' if peak else 'int'
    weights = df[f'flux_{suffix}_err']**-2
    fluxes = df[f"flux_{suffix}"]
    eta = (row['Nsrc'] / (row['Nsrc']-1)) * (
        (weights*fluxes**2).mean() - ((weights*fluxes).mean()**2 / weights.mean())
    )
    return eta


def calculate_de_ruiter(row):

    ra_1 = row.ra_skyc1
    ra_2 = row.ra_skyc2

    # avoid wrapping issues
    if ra_1 > 270. or ra_2 > 270.:
        ra_1 -= 180.
        ra_2 -= 180.

    elif ra_1 < 90. or ra_2 < 90.:
        ra_1 += 180.
        ra_2 += 180.

    ra_1 = np.deg2rad(ra_1)
    ra_2 = np.deg2rad(ra_2)

    ra_1_err = np.deg2rad(row.uncertainty_ew_skyc1)
    ra_2_err = np.deg2rad(row.uncertainty_ew_skyc2)

    dec_1 = np.deg2rad(row.dec_skyc1)
    dec_2 = np.deg2rad(row.dec_skyc2)

    dec_1_err = np.deg2rad(row.uncertainty_ns_skyc1)
    dec_2_err = np.deg2rad(row.uncertainty_ns_skyc2)

    dr1 = (ra_1 - ra_2)*(ra_1 - ra_2)
    dr1_1 = np.cos((dec_1 + dec_2)/2.)
    dr1 *= (dr1_1 * dr1_1)
    dr1 /= ((ra_1_err*ra_1_err) + (ra_2_err*ra_2_err))

    dr2 = (dec_1 - dec_2) * (dec_1 - dec_2)
    dr2 /= ((dec_1_err*dec_1_err) + (dec_2_err*dec_2_err))

    dr = np.sqrt(dr1 + dr2)

    return dr


def groupby_funcs(row, first_img):
    # calculated average ra, dec, fluxes and metrics
    d = {}
    d['wavg_ra'] = row.interim_ew.sum() / row.weight_ew.sum()
    d['wavg_dec'] = row.interim_ns.sum() / row.weight_ns.sum()
    d['wavg_uncertainty_ew'] = 1./np.sqrt(row.weight_ew.sum())
    d['wavg_uncertainty_ns'] = 1./np.sqrt(row.weight_ns.sum())
    for col in ['avg_flux_int', 'avg_flux_peak']:
        d[col] = row[col.split('_', 1)[1]].mean()
    d['max_flux_peak'] = row['flux_peak'].max()

    for col in ['flux_int', 'flux_peak']:
        d[f'{col}_sq'] = (row[col]**2).mean()
    d['Nsrc'] = row['id'].count()
    d['v_int'] = row["flux_int"].std() / row["flux_int"].mean()
    d['v_peak'] = row["flux_peak"].std() / row["flux_peak"].mean()
    d['eta_int'] = get_eta_metric(d, row)
    d['eta_peak'] = get_eta_metric(d, row, peak=True)
    # remove not used cols
    for col in ['flux_int_sq', 'flux_peak_sq']:
        d.pop(col)
    d.pop('Nsrc')
    # set new source
    d['new'] = False if first_img in row['img'].values else True
    return pd.Series(d)


def get_source_models(row, pipeline_run=None):
    name = f"src_{deg2hms(row['wavg_ra'])}{deg2dms(row['wavg_dec'])}"
    src = Source()
    src.run = pipeline_run
    src.name = name
    for fld in src._meta.get_fields():
        if getattr(fld, 'attname', None) and fld.attname in row.index:
            setattr(src, fld.attname, row[fld.attname])
    return src


def association(p_run, images, meas_dj_obj, limit, dr_limit, bw_limit, method):

    logger.info(
        "Association mode selected: %s.", method
    )

    if method == 'basic':
        sources_df = association_basic(
            p_run,
            images,
            meas_dj_obj,
            limit
        )
    elif method == 'advanced':
        sources_df = association_advanced(
            p_run,
            images,
            meas_dj_obj,
            dr_limit,
            bw_limit
        )
    else:
        raise Exception((
            'ASSOCIATION_METHOD not recongised.'
        ))

    # ra and dec columns are actually the average over each iteration
    # so remove ave ra and ave dec used for calculation and use
    # ra_source and dec_source columns
    sources_df = (
        sources_df.drop(['ra', 'dec'], axis=1)
        .rename(columns={'ra_source':'ra', 'dec_source':'dec'})
    )

    # calculate source fields
    logger.info(
        "Calculating statistics for %i sources...",
        sources_df.source.unique().shape[0]
    )
    srcs_df = sources_df.groupby('source').apply(
        groupby_funcs, first_img=images[0].name
    )
    # fill NaNs as resulted from calculated metrics with 0
    srcs_df = srcs_df.fillna(0.)

    # generate the source models
    srcs_df['src_dj'] = srcs_df.apply(
        get_source_models,
        axis=1,
        pipeline_run=p_run
    )
    # create sources in DB
    # TODO remove deleting existing sources
    if Source.objects.filter(run=p_run).exists():
        logger.info('removing objects from previous pipeline run')
        n_del, detail_del = Source.objects.filter(run=p_run).delete()
        logger.info(
            ('deleting all sources and related objects for this run. '
             'Total objects deleted: %i'),
            n_del,
        )
        logger.debug('(type, #deleted): %s', detail_del)

    logger.info('uploading associations to db')
    batch_size = 10_000
    for idx in range(0, srcs_df.src_dj.size, batch_size):
        out_bulk = Source.objects.bulk_create(
            srcs_df.src_dj.iloc[idx : idx + batch_size].tolist(),
            batch_size
        )
        logger.info('bulk created #%i sources', len(out_bulk))

    sources_df = (
        sources_df.merge(srcs_df, on='source')
        .merge(meas_dj_obj, on='id')
    )
    del srcs_df

    # Create Associan objects (linking measurements into single sources)
    # and insert in DB
    sources_df['assoc_dj'] = sources_df.apply(
        lambda row: Association(
            meas=row['meas_dj'],
            source=row['src_dj']
        ), axis=1
    )
    batch_size = 10_000
    for idx in range(0, sources_df.assoc_dj.size, batch_size):
        out_bulk = Association.objects.bulk_create(
            sources_df.assoc_dj.iloc[idx : idx + batch_size].tolist(),
            batch_size
        )
        logger.info('bulk created #%i associations', len(out_bulk))

def association_basic(p_run, images, meas_dj_obj, limit):
    # read the needed sources fields
    cols = [
        'id',
        'ra',
        'uncertainty_ew',
        "weight_ew",
        'dec',
        'uncertainty_ns',
        "weight_ns",
        'flux_int',
        'flux_int_err',
        'flux_peak',
        'flux_peak_err'
    ]
    skyc1_srcs = pd.read_parquet(
        images[0].measurements_path,
        columns=cols
    )
    skyc1_srcs['img'] = images[0].name
    # these are the first 'sources'
    skyc1_srcs['source'] = skyc1_srcs.index + 1
    skyc1_srcs['ra_source'] = skyc1_srcs.ra
    skyc1_srcs['uncertainty_ew_source'] = skyc1_srcs.uncertainty_ew
    skyc1_srcs['dec_source'] = skyc1_srcs.dec
    skyc1_srcs['uncertainty_ns_source'] = skyc1_srcs.uncertainty_ns
    skyc1_srcs['d2d'] = 0.0
    # create base catalogue
    skyc1 = SkyCoord(
        ra=skyc1_srcs.ra * u.degree,
        dec=skyc1_srcs.dec * u.degree
    )
    # initialise the sources dataframe using first image as base
    sources_df = skyc1_srcs.copy()
    for it, image in enumerate(images[1:]):
        logger.info('Association iteration: #%i', (it + 1))
        # load skyc2 source measurements and create SkyCoord
        skyc2_srcs = pd.read_parquet(
            image.measurements_path,
            columns=cols
        )
        skyc2_srcs['img'] = image.name
        skyc2_srcs['source'] = -1
        skyc2_srcs['ra_source'] = skyc2_srcs.ra
        skyc2_srcs['uncertainty_ew_source'] = skyc2_srcs.uncertainty_ew
        skyc2_srcs['dec_source'] = skyc2_srcs.dec
        skyc2_srcs['uncertainty_ns_source'] = skyc2_srcs.uncertainty_ns
        skyc2_srcs['d2d'] = 0.0
        skyc2 = SkyCoord(
            ra=skyc2_srcs.ra * u.degree,
            dec=skyc2_srcs.dec * u.degree
        )
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
        # this would mean that multiple sources in skyc2 have been matched to the same base source
        # we want to keep closest match and move the other match(es) back to having a -1 src id
        temp_matched_skyc2 = skyc2_srcs.dropna()
        if temp_matched_skyc2.source.unique().shape[0] != temp_matched_skyc2.source.shape[0]:
            logger.info("Double matches detected, cleaning...")
            # get the value counts
            cnts = temp_matched_skyc2[
                temp_matched_skyc2.source != -1
            ].source.value_counts()
            # and the src ids that are doubled
            multi_srcs = cnts[cnts > 1].index.values

            # now we have the src values which are doubled.
            # make the nearest match have the original src id
            # give the other matched source a new src id
            for i, msrc in enumerate(multi_srcs):
                # obtain the current start src elem
                start_elem = sources_df.source.max() + 1.
                skyc2_srcs_cut = skyc2_srcs[skyc2_srcs.source == msrc]
                min_d2d_idx = skyc2_srcs_cut.d2d.idxmin()
                # set the other indexes to a new src id
                # need to add copies of skyc1 source into the source_df
                # get the index of the skyc1 source
                skyc1_source_index = skyc1_srcs[skyc1_srcs.source == msrc].index.values[0]
                num_to_add = skyc2_srcs_cut.index.shape[0] - 1
                # copy it n times needed
                skyc1_srcs_toadd = skyc1_srcs.loc[[skyc1_source_index for i in range(num_to_add)]]
                # Appy new src ids to copies
                skyc1_srcs_toadd.source = np.arange(start_elem, start_elem + num_to_add)
                # Change skyc2 sources to new src ids
                idx_to_change = skyc2_srcs_cut.index.values[
                    skyc2_srcs_cut.index.values != min_d2d_idx
                ]
                skyc2_srcs.loc[idx_to_change, 'source'] = skyc1_srcs_toadd.source.values
                # append copies to source_df
                sources_df = sources_df.append(skyc1_srcs_toadd, ignore_index=True)
            logger.info("Cleaned %i double matches.", i + 1)

        del temp_matched_skyc2

        logger.info(
            "Updating sources catalogue with new sources..."
        )
        # update the src numbers for those sources in skyc2 with no match
        # using the max current src as the start and incrementing by one
        start_elem = sources_df.source.max() + 1.
        nan_sel = (skyc2_srcs.source == -1).values
        skyc2_srcs.loc[nan_sel, 'source'] = (
            np.arange(start_elem, start_elem + skyc2_srcs.loc[nan_sel].shape[0])
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

        logger.info(
            "Calculating weighted average RA and Dec for sources..."
        )

        sources_df["interim_ew"] = sources_df.ra * sources_df.weight_ew
        sources_df["interim_ns"] = sources_df.dec * sources_df.weight_ns

        tmp_srcs_df = (
            sources_df.loc[sources_df.source != -1, [
                'ra', 'dec', 'uncertainty_ew', 'uncertainty_ns', 'source', 'interim_ew',
                'interim_ns', 'weight_ew', 'weight_ns'
            ]]
            .groupby('source')
        )

        wm_ra = tmp_srcs_df['interim_ew'].sum() / tmp_srcs_df['weight_ew'].sum()
        wm_uncertainty_ew = 1./np.sqrt(tmp_srcs_df["weight_ew"].sum())

        wm_dec = tmp_srcs_df['interim_ns'].sum() / tmp_srcs_df['weight_ns'].sum()
        wm_uncertainty_ns = 1./np.sqrt(tmp_srcs_df["weight_ns"].sum())

        weighted_df = pd.concat(
            [wm_ra, wm_uncertainty_ew, wm_dec, wm_uncertainty_ns], axis=1, sort=False
        ).reset_index().rename(columns={
            0: "ra",
            "weight_ew": "uncertainty_ew",
            1: "dec",
            "weight_ns": "uncertainty_ns"
        })

        logger.info(
            "Finalising base sources catalogue ready for next iteration..."
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
        skyc1_srcs.ra = skyc1_srcs.ra_skyc2
        skyc1_srcs.dec = skyc1_srcs.dec_skyc2
        skyc1_srcs.uncertainty_ew = skyc1_srcs.uncertainty_ew_skyc2
        skyc1_srcs.uncertainty_ns = skyc1_srcs.uncertainty_ns_skyc2
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
            ra=skyc1_srcs.ra * u.degree,
            dec=skyc1_srcs.dec * u.degree
        )
        logger.info('Association iteration: #%i complete.', (it + 1))

    return sources_df

def association_advanced(p_run, images, meas_dj_obj, dr_limit, bw_limit):
    # read the needed sources fields
    cols = [
        'id',
        'ra',
        'uncertainty_ew',
        "weight_ew",
        'dec',
        'uncertainty_ns',
        "weight_ns",
        'flux_int',
        'flux_int_err',
        'flux_peak',
        'flux_peak_err'
    ]
    skyc1_srcs = pd.read_parquet(
        images[0].measurements_path,
        columns=cols
    )
    skyc1_srcs['img'] = images[0].name
    # these are the first 'sources'
    skyc1_srcs['source'] = skyc1_srcs.index + 1
    skyc1_srcs['ra_source'] = skyc1_srcs.ra
    skyc1_srcs['uncertainty_ew_source'] = skyc1_srcs.uncertainty_ew
    skyc1_srcs['dec_source'] = skyc1_srcs.dec
    skyc1_srcs['uncertainty_ns_source'] = skyc1_srcs.uncertainty_ns
    skyc1_srcs['d2d'] = 0.0
    # create base catalogue
    skyc1 = SkyCoord(
        ra=skyc1_srcs.ra * u.degree,
        dec=skyc1_srcs.dec * u.degree
    )
    # initialise the sources dataframe using first image as base
    sources_df = skyc1_srcs.copy()
    for it, image in enumerate(images[1:]):
        logger.info('Association iteration: #%i', (it + 1))
        # load skyc2 source measurements and create SkyCoord
        skyc2_srcs = pd.read_parquet(
            image.measurements_path,
            columns=cols
        )
        skyc2_srcs['img'] = image.name
        skyc2_srcs['source'] = -1
        skyc2_srcs['ra_source'] = skyc2_srcs.ra
        skyc2_srcs['uncertainty_ew_source'] = skyc2_srcs.uncertainty_ew
        skyc2_srcs['dec_source'] = skyc2_srcs.dec
        skyc2_srcs['uncertainty_ns_source'] = skyc2_srcs.uncertainty_ns
        skyc2_srcs['d2d'] = 0.0
        skyc2 = SkyCoord(
            ra=skyc2_srcs.ra * u.degree,
            dec=skyc2_srcs.dec * u.degree
        )
        # Step 1: get matches within semimajor axis of image.
        bw_max = Angle(bw_limit * (image.beam_bmaj * 3600. / 2.) * u.arcsec)
        idx_skyc1, idx_skyc2, d2d, d3d = skyc2.search_around_sky(skyc1, bw_max)
        # Step 2: Apply the beamwidth limit
        sel = d2d <= bw_max

        skyc2_srcs.loc[idx_skyc2[sel], 'd2d'] = d2d[sel].arcsec

        # Step 3: merge the candidates so the de ruiter can be calculated
        temp_skyc1_srcs = skyc1_srcs.loc[idx_skyc1[sel]]
        temp_skyc1_srcs = temp_skyc1_srcs.reset_index().rename(
            columns={"index":"index_old"}
        )
        temp_skyc2_srcs = skyc2_srcs.loc[idx_skyc2[sel]]
        temp_skyc2_srcs = temp_skyc2_srcs.reset_index().rename(
            columns={"index":"index_old"}
        )
        temp_srcs = temp_skyc1_srcs.merge(
            temp_skyc2_srcs,
            left_index=True,
            right_index=True,
            suffixes=('_skyc1', '_skyc2')
        )

        # Step 4: Calculate and perform De Ruiter radius cut
        temp_srcs['dr'] = temp_srcs.apply(calculate_de_ruiter, axis=1)
        temp_srcs = temp_srcs[temp_srcs.dr <= dr_limit]

        # Now have the 'good' matches
        # Step 5: Check for one-to-many, many-to-one and many-to-many associations

        # First many-to-many
        # Select those where the extracted source is listed more than once
        skyc2_cnts = temp_srcs.index_old_skyc2.value_counts()
        # and the src ids that are doubled
        multi_skyc2_srcs = skyc2_cnts[skyc2_cnts > 1].index.values
        # and of these get those that have a source id that is listed more than
        # once in the temps_srcs df
        # first we need a list of double source_ids
        skyc1_cnts = temp_srcs.source_skyc1.value_counts()
        multi_skyc1_srcs = skyc1_cnts[skyc1_cnts > 1].index.values
        # and make the selection
        m_to_m = temp_srcs[
            (temp_srcs.index_old_skyc2.isin(multi_skyc2_srcs)) &
            (temp_srcs.source_skyc1.isin(multi_skyc1_srcs))
        ].reset_index()
        if m_to_m.shape[0] == 0:
            logger.debug("No many-to-many assocations")
        else:
            logger.debug("%i many-to-many assocations", m_to_m.shape[0])
            # get the minimum de ruiter value for each extracted source
            m_to_m_temp = m_to_m.groupby('index_old_skyc2')['dr']
            m_to_m.loc[m_to_m.index.values,'min_dr'] = m_to_m_temp.transform('min')
            del m_to_m_temp
            # get the ids of those crossmatches that are larger than the minimum
            m_to_m_to_drop = m_to_m[m_to_m.dr != m_to_m.min_dr].index.values
            # and drop these from the temp_srcs
            temp_srcs.drop(
                m_to_m_to_drop, inplace=True
            )
            temp_srcs.reset_index(
                drop=True, inplace=True
            )

        # Next one-to-many
        # Get the sources which are doubled
        skyc1_cnts = temp_srcs.source_skyc1.value_counts()
        multi_skyc1_srcs = skyc1_cnts[skyc1_cnts > 1].index.values
        if multi_skyc1_srcs.shape[0] == 0:
            logger.debug("no one-to-many associations")
        else:
            logger.debug("%i one-to-many associations", multi_skyc1_srcs.shape[0])
            # go through the doubles and
            # 1. Keep the closest de ruiter as the primary id
            # 2. Increment a new source id for others
            # 3. Add a copy of the base source into sources.
            for i, mskyc1 in enumerate(multi_skyc1_srcs):
                # define a start src id for new forks
                start_src_id = sources_df.source.max() + 1
                # Make the selection
                o_to_m_temp = temp_srcs[temp_srcs.source_skyc1 == mskyc1]
                # Get the min dr idx
                o_to_m_min_dr_idx = o_to_m_temp.dr.idxmin()
                # Select the others
                idx_to_change = o_to_m_temp.index.values[
                    o_to_m_temp.index.values != o_to_m_min_dr_idx
                ]
                # Copy the original skyc1 object ready to append
                sky1_idx_to_copy = o_to_m_temp.index_old_skyc1.iloc[0]
                num_to_add = idx_to_change.shape[0]
                skyc1_srcs_toadd = skyc1_srcs.loc[[sky1_idx_to_copy for i in range(num_to_add)]]
                # Define new source ids
                new_src_ids = np.arange(start_src_id, start_src_id + num_to_add)
                # Apply to the temp
                temp_srcs.loc[idx_to_change, 'source_skyc1'] = new_src_ids
                # And apply to the new rows to add to sources (copies of the skyc1 source)
                skyc1_srcs_toadd.source = new_src_ids
                # append copies of skyc1 to source_df
                sources_df = sources_df.append(skyc1_srcs_toadd, ignore_index=True)

        # Finally many-to-one associations, the opposite of above
        # But we don't have to create new ids for these so it's much simpler
        # In fact we don't need to do anything but lets get the number for debugging.
        skyc2_cnts = temp_srcs.index_old_skyc2.value_counts()
        multi_skyc2_srcs = skyc2_cnts[skyc2_cnts > 1].index.values
        if multi_skyc2_srcs.shape[0] == 0:
            logger.debug("no many-to-one associations")
        else:
            logger.debug("%i many-to-one associations", multi_skyc2_srcs.shape[0])

        # Now everything in place to append

        # First the skyc2 sources with a match.
        # This is created from the temp_srcs df.
        # This will take care of the extra skyc2 sources needed.

        skyc2_srcs_toappend = skyc2_srcs.loc[
            temp_srcs.index_old_skyc2.values
        ].reset_index(drop=True)

        skyc2_srcs_toappend["source"] = temp_srcs.source_skyc1.values

        # and get the skyc2 sources with no match

        logger.info(
            "Updating sources catalogue with new sources..."
        )

        new_sources = skyc2_srcs.loc[
            skyc2_srcs.index.difference(
                temp_srcs.index_old_skyc2.values
            )
        ].reset_index(drop=True)

        # update the src numbers for those sources in skyc2 with no match
        # using the max current src as the start and incrementing by one
        start_elem = sources_df.source.max() + 1.
        new_sources["source"] = np.arange(
            start_elem, start_elem + new_sources.shape[0]
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

        logger.info(
            "Calculating weighted average RA and Dec for sources..."
        )
        sources_df["interim_ew"] = sources_df.ra * sources_df.weight_ew
        sources_df["interim_ns"] = sources_df.dec * sources_df.weight_ns

        tmp_srcs_df = (
            sources_df.loc[sources_df.source != -1, [
                'ra', 'dec', 'uncertainty_ew', 'uncertainty_ns', 'source', 'interim_ew',
                'interim_ns', 'weight_ew', 'weight_ns'
            ]]
            .groupby('source')
        )

        wm_ra = tmp_srcs_df['interim_ew'].sum() / tmp_srcs_df['weight_ew'].sum()
        wm_uncertainty_ew = 1./np.sqrt(tmp_srcs_df["weight_ew"].sum())

        wm_dec = tmp_srcs_df['interim_ns'].sum() / tmp_srcs_df['weight_ns'].sum()
        wm_uncertainty_ns = 1./np.sqrt(tmp_srcs_df["weight_ns"].sum())

        weighted_df = pd.concat(
            [wm_ra, wm_uncertainty_ew, wm_dec, wm_uncertainty_ns], axis=1, sort=False
        ).reset_index().rename(columns={
            0: "ra",
            "weight_ew": "uncertainty_ew",
            1: "dec",
            "weight_ns": "uncertainty_ns"
        })

        logger.info(
            "Finalising base sources catalogue ready for next iteration..."
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
        skyc1_srcs.ra = skyc1_srcs.ra_skyc2
        skyc1_srcs.dec = skyc1_srcs.dec_skyc2
        skyc1_srcs.uncertainty_ew = skyc1_srcs.uncertainty_ew_skyc2
        skyc1_srcs.uncertainty_ns = skyc1_srcs.uncertainty_ns_skyc2
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
            ra=skyc1_srcs.ra * u.degree,
            dec=skyc1_srcs.dec * u.degree
        )
        logger.info('Association iteration: #%i complete.', (it + 1))

    return sources_df
