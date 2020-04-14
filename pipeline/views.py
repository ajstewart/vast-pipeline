import logging

from django.db.models import Count, F
from django.shortcuts import render
from rest_framework.viewsets import ModelViewSet

from .models import Image, Measurement, Run, Source
from .serializers import (
    ImageSerializer, MeasurementSerializer, RunSerializer,
    SourceSerializer
)
from .utils.utils import deg2dms, deg2hms


logger = logging.getLogger(__name__)


# Runs table
def RunIndex(request):
    colsfields = []
    for col in ['time', 'name', 'path', 'comment', 'n_images', 'n_sources']:
        if col == 'name':
            colsfields.append({
                'data': col, 'render': {
                    'url': {
                        'prefix': '/piperuns/', 'col':'name'
                    }
                }
            })
        else:
            colsfields.append({'data': col})
    return render(
        request,
        'generic_table.html',
        {
            'text': {
                'title': 'Pipeline Runs',
                'description': 'List of pipeline runs below',
                'breadcrumb': {'title': 'Pipeline Runs', 'url': request.path},
            },
            'datatable': {
                'api': '/api/piperuns/?format=datatables',
                'colsFields': colsfields,
                'colsNames': [
                    'Run Datetime','Name','Path','Comment','Nr Images',
                    'Nr Sources'
                ],
                'search': True,
            }
        }
    )


class RunViewSet(ModelViewSet):
    queryset = Run.objects.annotate(
        n_images=Count("image", distinct=True),
        n_sources=Count("source", distinct=True),
    )
    serializer_class = RunSerializer


# Run detail
def RunDetail(request, id):
    p_run = Run.objects.filter(id=id).values().get()
    p_run['nr_imgs'] = Image.objects.filter(run__id=p_run['id']).count()
    p_run['nr_srcs'] = Source.objects.filter(run__id=p_run['id']).count()
    p_run['nr_meas'] = Measurement.objects.filter(image__run__id=p_run['id']).count()
    p_run['new_srcs'] = Source.objects.filter(
        run__id=p_run['id'],
        new=True,
    ).count()
    return render(request, 'run_detail.html', {'p_run': p_run})


# Images table
def ImageIndex(request):
    cols = ['datetime', 'name', 'ra', 'dec']
    return render(
        request,
        'generic_table.html',
        {
            'text': {
                'title': 'Images',
                'description': 'List of images below',
                'breadcrumb': {'title': 'Images', 'url': request.path},
            },
            'datatable': {
                'api': '/api/images/?format=datatables',
                'colsFields': [{'data': x} for x in cols],
                'colsNames': ['Time','Name','RA','DEC'],
                'search': True,
            }
        }
    )


class ImageViewSet(ModelViewSet):
    queryset = Image.objects.all()
    serializer_class = ImageSerializer


# Measurements table
def MeasurementIndex(request):
    fields = [
        'name',
        'ra',
        'ra_err',
        'uncertainty_ew',
        'dec',
        'dec_err',
        'uncertainty_ns',
        'flux_int',
        'flux_peak'
    ]
    colsfields = []
    float_fields = {
        'ra': {
            'precision': 4,
            'scale': 1,
        },
        'ra_err': {
            'precision': 4,
            'scale': 3600.,
        },
        'uncertainty_ew': {
            'precision': 4,
            'scale': 3600.,
        },
        'dec': {
            'precision': 4,
            'scale': 1,
        },
        'dec_err': {
            'precision': 4,
            'scale': 3600,
        },
        'uncertainty_ns': {
            'precision': 4,
            'scale': 3600.,
        },
        'flux_int': {
            'precision': 2,
            'scale': 1,
        },
        'flux_peak': {
            'precision': 2,
            'scale': 1,
        },
    }
    for col in fields:
        if col == 'name':
            colsfields.append({
                'data': col, 'render': {
                    'url': {
                        'prefix': '/measurements/',
                        'col': 'name'
                    }
                }
            })
        elif col in float_fields:
            colsfields.append({
                'data': col,
                'render': {
                    'float': {
                        'col': col,
                        'precision': float_fields[col]['precision'],
                        'scale': float_fields[col]['scale'],
                    }
                }
            })
        else:
            colsfields.append({'data': col})
    return render(
        request,
        'generic_table.html',
        {
            'text': {
                'title': 'Image Data Measurements',
                'description': 'List of source measurements below',
                'breadcrumb': {'title': 'Measurements', 'url': request.path},
            },
            'datatable': {
                'api': '/api/measurements/?format=datatables',
                'colsFields': colsfields,
                'colsNames': [
                    'Name',
                    'RA (deg)',
                    'RA Error (arcsec)',
                    'Uncertainty EW (arcsec)',
                    'Dec (deg)',
                    'Dec Error (arcsec)',
                    'Uncertainty NS (arcsec)',
                    'Int. Flux (mJy)',
                    'Peak Flux (mJy/beam)'
                ],
                'search': True,
            }
        }
    )


class MeasurementViewSet(ModelViewSet):
    queryset = Measurement.objects.all()
    serializer_class = MeasurementSerializer

    def get_queryset(self):
        run_id = self.request.query_params.get('run_id', None)
        return self.queryset.filter(source__id=run_id) if run_id else self.queryset


# Sources table
def SourceIndex(request):
    fields = [
        'name',
        'comment',
        'wavg_ra',
        'wavg_dec',
        'avg_flux_int',
        'avg_flux_peak',
        'max_flux_peak',
        'measurements',
        'v_int',
        'eta_int',
        'v_peak',
        'eta_peak',
        'new'
    ]
    float_fields = {
        'v_int': {
            'precision': 2,
            'scale': 1,
        },
        'eta_int': {
            'precision': 2,
            'scale': 1,
        },
        'v_peak': {
            'precision': 2,
            'scale': 1,
        },
        'eta_peak': {
            'precision': 2,
            'scale': 1,
        },
        'avg_flux_int': {
            'precision': 3,
            'scale': 1,
        },
        'avg_flux_peak': {
            'precision': 3,
            'scale': 1,
        },
        'max_flux_peak': {
            'precision': 3,
            'scale': 1,
        },
    }
    colsfields = []
    for col in fields:
        if col == 'name':
            colsfields.append({
                'data': col, 'render': {
                    'url': {
                        'prefix': '/sources/',
                        'col': 'name'
                    }
                }
            })
        elif col in float_fields:
            colsfields.append({
                'data': col,
                'render': {
                    'float': {
                        'col': col,
                        'precision': float_fields[col]['precision'],
                        'scale': float_fields[col]['scale'],
                    }
                }
            })
        else:
            colsfields.append({'data': col})


    return render(
        request,
        'generic_table.html',
        {
            'text': {
                'title': 'Sources',
                'description': 'List of all sources below',
                'breadcrumb': {'title': 'Sources', 'url': request.path},
            },
            'datatable': {
                'api': '/api/sources/?format=datatables',
                'colsFields': colsfields,
                'colsNames': [
                    'Name',
                    'Comment',
                    'W. Avg. RA',
                    'W. Avg. Dec',
                    'Avg. Int. Flux (mJy)',
                    'Avg. Peak Flux (mJy/beam)',
                    'Max Peak Flux (mJy/beam)',
                    'Datapoints',
                    'V int flux',
                    '\u03B7 int flux',
                    'V peak flux',
                    '\u03B7 peak flux',
                    'New Source',
                ],
                'search': False,
            }
        }
    )


class SourceViewSet(ModelViewSet):
    serializer_class = SourceSerializer

    def get_queryset(self):
        qs = Source.objects.annotate(measurements=Count("measurement"))

        qry_dict = {}
        p_run = self.request.query_params.get('run')
        if p_run:
            qry_dict['run__name'] = p_run

        flux_qry_flds = ['avg_flux_int', 'avg_flux_peak', 'v_int', 'v_peak']
        for fld in flux_qry_flds:
            for limit in ['max', 'min']:
                val = self.request.query_params.get(limit + '_' + fld)
                if val:
                    ky = fld + '__lte' if limit == 'max' else fld + '__gte'
                    qry_dict[ky] = val

        measurements = self.request.query_params.get('meas')
        if measurements:
            qry_dict['measurements'] = measurements

        if 'newsrc' in self.request.query_params:
            qry_dict['new'] = True

        if qry_dict:
            qs = qs.filter(**qry_dict)

        radius = self.request.query_params.get('radius')
        wavg_ra = self.request.query_params.get('ra')
        wavg_dec = self.request.query_params.get('dec')
        if wavg_ra and wavg_dec and radius:
            qs = qs.cone_search(wavg_ra, wavg_dec, radius)

        return qs


# Sources Query
def SourceQuery(request):
    fields = [
        'name',
        'comment',
        'wavg_ra',
        'wavg_dec',
        'avg_flux_int',
        'avg_flux_peak',
        'max_flux_peak',
        'measurements',
        'v_int',
        'eta_int',
        'v_peak',
        'eta_peak',
        'new'
    ]
    float_fields = {
        'v_int': {
            'precision': 2,
            'scale': 1,
        },
        'eta_int': {
            'precision': 2,
            'scale': 1,
        },
        'v_peak': {
            'precision': 2,
            'scale': 1,
        },
        'eta_peak': {
            'precision': 2,
            'scale': 1,
        },
        'avg_flux_int': {
            'precision': 3,
            'scale': 1,
        },
        'avg_flux_peak': {
            'precision': 3,
            'scale': 1,
        },
        'max_flux_peak': {
            'precision': 3,
            'scale': 1,
        },
    }
    colsfields = []
    for col in fields:
        if col == 'name':
            colsfields.append({
                'data': col, 'render': {
                    'url': {
                        'prefix': '/sources/',
                        'col':'name'
                    }
                }
            })
        elif col in float_fields:
            colsfields.append({
                'data': col,
                'render': {
                    'float': {
                        'col': col,
                        'precision': float_fields[col]['precision'],
                        'scale': float_fields[col]['scale'],
                    }
                }
            })
        else:
            colsfields.append({'data': col})

    # get all pipeline run names
    p_runs =  list(Run.objects.values('name').all())

    return render(
        request,
        'sources_query.html',
        {
            'breadcrumb': {'title': 'Sources', 'url': request.path},
            # 'text': {
            #     'title': 'Sources',
            #     'description': 'List of all sources below',
            # },
            'runs': p_runs,
            'datatable': {
                'api': '/api/sources/?format=datatables',
                'colsFields': colsfields,
                'colsNames': [
                    'Name',
                    'Comment',
                    'W. Avg. RA',
                    'W. Avg. Dec',
                    'Avg. Int. Flux (mJy)',
                    'Avg. Peak Flux (mJy/beam)',
                    'Max Peak Flux (mJy/beam)',
                    'Datapoints',
                    'V int flux',
                    '\u03B7 int flux',
                    'V peak flux',
                    '\u03B7 peak flux',
                    'New Source',
                ],
                'search': False,
            }
        }
    )


# Source detail
def SourceDetail(request, id, action=None):
    # source data
    source = Source.objects.all()
    if action:
        if action == 'next':
            src = source.filter(id__gt=id)
            if src.exists():
                source = src.annotate(
                    run_name=F('run__name')
                ).values().first()
            else:
                source = source.filter(id=id).annotate(
                    run_name=F('run__name')
                ).values().get()
        elif action == 'prev':
            src = source.filter(id__lt=id)
            if src.exists():
                source = src.annotate(
                    run_name=F('run__name')
                ).values().last()
            else:
                source = source.filter(id=id).annotate(
                    run_name=F('run__name')
                ).values().get()
    else:
        source = source.filter(id=id).annotate(
            run_name=F('run__name')
        ).values().get()
    source['aladin_ra'] = source['wavg_ra']
    source['aladin_dec'] = source['wavg_dec']
    source['wavg_ra'] = deg2hms(source['wavg_ra'], hms_format=True)
    source['wavg_dec'] = deg2dms(source['wavg_dec'], dms_format=True)
    source['datatable'] = {'colsNames': [
        'Name',
        'Date',
        'Image',
        'RA',
        'RA Error',
        'Dec',
        'Dec Error',
        'Int. Flux (mJy)',
        'Int. Flux Error (mJy)',
        'Peak Flux (mJy/beam)',
        'Peak Flux Error (mJy/beam)',
    ]}

    # source data
    cols = [
        'name',
        'ra',
        'ra_err',
        'dec',
        'dec_err',
        'flux_int',
        'flux_int_err',
        'flux_peak',
        'flux_peak_err',
        'datetime',
        'image_name',
    ]
    measurements = list(
        Measurement.objects.filter(source__id=id).annotate(
            datetime=F('image__datetime'),
            image_name=F('image__name'),
        ).order_by('datetime').values(*tuple(cols))
    )
    for one_m in measurements:
        one_m['datetime'] = one_m['datetime'].isoformat()

    # add source count
    source['measurements'] = len(measurements)
    # add the data for the datatable api
    measurements = {
        'dataQuery': measurements,
        'colsFields': [
            'name',
            'datetime',
            'image_name',
            'ra',
            'ra_err',
            'dec',
            'dec_err',
            'flux_int',
            'flux_int_err',
            'flux_peak',
            'flux_peak_err',
        ],
        'search': True,
        'order': [1, 'asc']
    }

    for i,val in enumerate(measurements['dataQuery']):
        for j in ['ra', 'dec', 'ra_err', 'dec_err']:
            measurements['dataQuery'][i][j] = "{:.4f}".format(val[j])
        for j in ['flux_int', 'flux_int_err', 'flux_peak', 'flux_peak_err']:
            measurements['dataQuery'][i][j] = "{:.3f}".format(val[j])

    print(measurements)
    context = {'source': source, 'measurements': measurements}
    return render(request, 'source_detail.html', context)


def MeasurementDetail(request, id, action=None):
    # source data
    measurement = Measurement.objects.all().order_by('id')
    if action:
        if action == 'next':
            msr = measurement.filter(id__gt=id)
            print(msr)
            if msr.exists():
                measurement = msr.annotate(
                    datetime=F('image__datetime'),
                    image_name=F('image__name'),
                ).values().first()
            else:
                measurement = measurement.filter(id=id).annotate(
                    datetime=F('image__datetime'),
                    image_name=F('image__name'),
                ).values().get()
        elif action == 'prev':
            msr = measurement.filter(id__lt=id)
            if msr.exists():
                measurement = msr.annotate(
                    datetime=F('image__datetime'),
                    image_name=F('image__name'),
                ).values().last()
            else:
                measurement = measurement.filter(id=id).annotate(
                    datetime=F('image__datetime'),
                    image_name=F('image__name'),
                ).values().get()
    else:
        measurement = measurement.filter(id=id).annotate(
            datetime=F('image__datetime'),
            image_name=F('image__name'),
        ).values().get()

    measurement['aladin_ra'] = measurement['ra']
    measurement['aladin_dec'] = measurement['dec']
    measurement['ra'] = deg2hms(measurement['ra'], hms_format=True)
    measurement['dec'] = deg2dms(measurement['dec'], dms_format=True)

    measurement['datetime'] = measurement['datetime'].isoformat()

    # add source count
    # add the data for the datatable api

    context = {'measurement': measurement}
    return render(request, 'measurement_detail.html', context)
