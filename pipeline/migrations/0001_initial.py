# Generated by Django 2.2.5 on 2020-02-27 02:34

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Association',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('probability', models.FloatField(default=1.0)),
            ],
        ),
        migrations.CreateModel(
            name='Band',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=12, unique=True)),
                ('frequency', models.IntegerField()),
                ('bandwidth', models.IntegerField()),
            ],
            options={
                'ordering': ['frequency'],
            },
        ),
        migrations.CreateModel(
            name='CrossMatch',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('manual', models.BooleanField()),
                ('distance', models.FloatField()),
                ('probability', models.FloatField()),
                ('comment', models.TextField(blank=True, default='', max_length=1000)),
            ],
        ),
        migrations.CreateModel(
            name='Image',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('measurements_path', models.FilePathField(db_column='meas_path', max_length=200)),
                ('polarisation', models.CharField(help_text='Polarisation of the image e.g. I,XX,YY,Q,U,V', max_length=2)),
                ('name', models.CharField(help_text='Name of the image', max_length=200)),
                ('path', models.FilePathField(help_text='Path to the file containing the image', max_length=500)),
                ('noise_path', models.CharField(blank=True, default='', help_text='Path to the file containing the RMS image', max_length=300)),
                ('background_path', models.CharField(blank=True, default='', help_text='Path to the file containing the background image', max_length=300)),
                ('valid', models.BooleanField(default=True, help_text='Is the image valid')),
                ('datetime', models.DateTimeField(help_text='Date of observation')),
                ('jd', models.FloatField(help_text='Julian date of the observation (days)')),
                ('duration', models.FloatField(default=0.0, help_text='Duration of the observation')),
                ('flux_gain', models.FloatField(default=1, help_text='Gain of the image, multiplicative factor to change the relative flux scale')),
                ('flux_gain_err', models.FloatField(default=0, help_text='Error on the image gain')),
                ('ra', models.FloatField(help_text='RA of the image centre (Deg)')),
                ('dec', models.FloatField(help_text='DEC of the image centre (Deg)')),
                ('fov_bmaj', models.FloatField(help_text='Field of view major axis (Deg)')),
                ('fov_bmin', models.FloatField(help_text='Field of view minor axis ')),
                ('radius_pixels', models.FloatField(help_text='Radius of the useable region of the image (pixels)')),
                ('beam_bmaj', models.FloatField(help_text='Major axis of image restoring beam (Deg)')),
                ('beam_bmin', models.FloatField(help_text='Minor axis of image restoring beam (Deg)')),
                ('beam_bpa', models.FloatField()),
                ('rms', models.FloatField(default=0, help_text='Background RMS based on sigma clipping of image data (mJy)')),
                ('flux_percentile', models.FloatField(default=0)),
                ('band', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='pipeline.Band')),
            ],
            options={
                'ordering': ['datetime'],
            },
        ),
        migrations.CreateModel(
            name='Run',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=64, unique=True, validators=[django.core.validators.RegexValidator(inverse_match=True, message='Name contains not allowed characters!', regex='[\\[@!#$%^&*()<>?/\\|}{~:\\] ]')])),
                ('time', models.DateTimeField(auto_now=True, help_text='Datetime of run')),
                ('path', models.FilePathField(max_length=200)),
                ('comment', models.TextField(blank=True, default='', max_length=1000)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Survey',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Name of the Survey e.g. NVSS', max_length=32, unique=True)),
                ('comment', models.TextField(blank=True, default='', max_length=1000)),
                ('frequency', models.IntegerField(help_text='Frequency of the survey')),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='SurveySource',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Name of the survey source', max_length=100)),
                ('ra', models.FloatField(help_text='RA of the survey source (Deg)')),
                ('ra_err', models.FloatField(verbose_name='RA error of the survey source (Deg)')),
                ('dec', models.FloatField(verbose_name='DEC of the survey source (Deg)')),
                ('dec_err', models.FloatField(verbose_name='DEC error of the survey source (Deg)')),
                ('bmaj', models.FloatField(help_text='The major axis of the Gaussian fit to the survey source (arcsecs)')),
                ('bmin', models.FloatField(help_text='The minor axis of the Gaussian fit to the survey source (arcsecs)')),
                ('pa', models.FloatField(help_text='Position angle of Gaussian fit east of north to bmaj (Deg)')),
                ('flux_peak', models.FloatField(help_text='Peak flux of the Guassian fit (Jy)')),
                ('flux_peak_err', models.FloatField(help_text='Peak flux error of the Gaussian fit (Jy)')),
                ('flux_int', models.FloatField(help_text='Integrated flux of the Guassian fit (Jy)')),
                ('flux_int_err', models.FloatField(help_text='Integrated flux of the Guassian fit (Jy)')),
                ('alpha', models.FloatField(default=0, help_text='Spectral index of the survey source')),
                ('image_name', models.CharField(blank=True, help_text='Name of survey image where measurement was made', max_length=100)),
                ('survey', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='pipeline.Survey')),
            ],
        ),
        migrations.CreateModel(
            name='Source',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('comment', models.TextField(blank=True, default='', max_length=1000)),
                ('new', models.BooleanField(default=False, help_text='New Source')),
                ('ave_ra', models.FloatField()),
                ('ave_dec', models.FloatField()),
                ('ave_flux_int', models.FloatField()),
                ('ave_flux_peak', models.FloatField()),
                ('max_flux_peak', models.FloatField()),
                ('v_int', models.FloatField(help_text='V metric for int flux')),
                ('v_peak', models.FloatField(help_text='V metric for peak flux')),
                ('eta_int', models.FloatField(help_text='Eta metric for int flux')),
                ('eta_peak', models.FloatField(help_text='Eta metric for peak flux')),
                ('cross_match_sources', models.ManyToManyField(through='pipeline.CrossMatch', to='pipeline.SurveySource')),
                ('run', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='pipeline.Run')),
            ],
        ),
        migrations.CreateModel(
            name='SkyRegion',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('centre_ra', models.FloatField()),
                ('centre_dec', models.FloatField()),
                ('xtr_radius', models.FloatField()),
                ('x', models.FloatField()),
                ('y', models.FloatField()),
                ('z', models.FloatField()),
                ('run', models.ManyToManyField(to='pipeline.Run')),
            ],
        ),
        migrations.CreateModel(
            name='Measurement',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=64, unique=True)),
                ('ra', models.FloatField(help_text='RA of the source (Deg)')),
                ('ra_err', models.FloatField(help_text='RA error of the source (Deg)')),
                ('dec', models.FloatField(help_text='DEC of the source (Deg)')),
                ('dec_err', models.FloatField(help_text='DEC error of the source (Deg)')),
                ('bmaj', models.FloatField(help_text='The major axis of the Gaussian fit to the source (Deg)')),
                ('err_bmaj', models.FloatField()),
                ('bmin', models.FloatField(help_text='The minor axis of the Gaussian fit to the source (Deg)')),
                ('err_bmin', models.FloatField()),
                ('pa', models.FloatField(help_text='Position angle of Gaussian fit east of north to bmaj (Deg)')),
                ('err_pa', models.FloatField()),
                ('flux_int', models.FloatField()),
                ('flux_int_err', models.FloatField()),
                ('flux_peak', models.FloatField()),
                ('flux_peak_err', models.FloatField()),
                ('chi_squared_fit', models.FloatField(db_column='chi2_fit', help_text='Chi-squared of the Guassian fit to the source')),
                ('spectral_index', models.FloatField(db_column='spectr_idx', help_text='In-band Selavy spectral index')),
                ('spectral_index_from_TT', models.BooleanField(db_column='spectr_idx_tt', default=False, help_text='True/False if the spectral index came from the taylor term came')),
                ('flag_c4', models.BooleanField(default=False, help_text='Fit flag from selavy')),
                ('has_siblings', models.BooleanField(default=False, help_text='Does the fit come from an island')),
                ('component_id', models.CharField(help_text='The ID of the component from which the source comes from', max_length=64)),
                ('island_id', models.CharField(help_text='The ID of the island from which the source comes from', max_length=64)),
                ('monitor', models.BooleanField(default=False, help_text='Are we monitoring this location')),
                ('persistent', models.BooleanField(default=False, help_text='Keep this source between pipeline runs')),
                ('quality', models.NullBooleanField(default=False, help_text='Is this a quality source for analysis purposes')),
                ('image', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='pipeline.Image')),
                ('source', models.ManyToManyField(through='pipeline.Association', to='pipeline.Source')),
            ],
            options={
                'ordering': ['ra'],
            },
        ),
        migrations.AddField(
            model_name='image',
            name='run',
            field=models.ManyToManyField(to='pipeline.Run'),
        ),
        migrations.AddField(
            model_name='image',
            name='skyreg',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='pipeline.SkyRegion'),
        ),
        migrations.AddField(
            model_name='crossmatch',
            name='source',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='pipeline.Source'),
        ),
        migrations.AddField(
            model_name='crossmatch',
            name='survey_source',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='pipeline.SurveySource'),
        ),
        migrations.AddField(
            model_name='association',
            name='meas',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='pipeline.Measurement'),
        ),
        migrations.AddField(
            model_name='association',
            name='source',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='pipeline.Source'),
        ),
    ]
