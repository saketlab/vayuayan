"""CPCB routes, written out here so a changed package constant fails the tests."""

BASE = "https://airquality.cpcb.gov.in"
NEW_REPOSITORY = f"{BASE}/caaqms-common/dataRepository"
FILE_PATH = f"{NEW_REPOSITORY}/file-path"
DOWNLOAD_LINK = f"{NEW_REPOSITORY}/get-download-link"
DOWNLOAD_FILE = f"{NEW_REPOSITORY}/download-excel-fileEnc"
LEGACY_DOWNLOAD = f"{BASE}/dataRepository/download_file"
LEGACY_FILE_PATH = f"{BASE}/dataRepository/file_Path"
LEGACY_STATION_LIST = f"{BASE}/dataRepository/all_india_stationlist"
OAUTH = f"{BASE}/api/security/oauth/token"
CUSTOM_QUERY = f"{BASE}/projectworkflow/client/custom/query"
DASHBOARD_STATIONS = f"{BASE}/aqi_dashboard/aqi_station_all_india"
DASHBOARD_PARAMETERS = f"{BASE}/aqi_dashboard/aqi_all_Parameters"
RSS = f"{BASE}/caaqms/iit_rss_feed_with_coordinates"

JSON_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}
FORM_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "q=0.8;application/json;q=0.9",
}

FILES = {"status": "success", "data": [{"filepath": "/x.xlsx", "year": "2024"}]}
RSS_FEED = {
    "country": [
        {
            "stateId": "Delhi",
            "citiesInState": [
                {
                    "cityId": "Delhi",
                    "stationsInCity": [
                        {"siteId": "site_1", "stationName": "ITO", "lastUpdate": "x"}
                    ],
                }
            ],
        }
    ]
}
