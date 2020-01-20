from django.urls import path, include
from django.views.generic import TemplateView
from rest_framework.routers import DefaultRouter

from . import views


app_name = 'pipeline'

router = DefaultRouter()
router.register(r'datasets', views.DatasetViewSet, 'api_datasets')
router.register(r'images', views.ImageViewSet, 'api_images')
router.register(r'sources', views.SourceViewSet, 'api_sources')

urlpatterns = [
    path('datasets', views.datasetIndex, name='dataset_index'),
    path('datasets/<int:pk>/', views.datasetDetail, name='dataset_detail'),
    path('images', views.imageIndex, name='image_index'),
    path('sources', views.sourceIndex, name='source_index'),
    path('api/', include(router.urls))
]
