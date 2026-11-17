"""surfcast: pull surf forecast data from the command line."""

from surfcast.client import SurfForecastClient, fetch_forecast
from surfcast.models import Forecast, ForecastHour, Spot

__all__ = ["Forecast", "ForecastHour", "Spot", "SurfForecastClient", "fetch_forecast"]
__version__ = "0.1.0"
