# updaterepo daemon

updaterepod is a small application derived from yum and updaterepo.py (https://github.com/heroldus/updaterepo).

It relies on inotify to watch a defined set of directories for changes (RPM files) and update the repository metadata accordingly.

By design, as updaterepod is largely based on updaterepo.py, only the SQLite databases will be updated upon changes. This massively speed things up.

## Configuration
By default, the main configuration file is located at /etc/updaterepod/config.yaml.

Below, the supported options:

Option  | Type | Description
------------- | ------------- | -------------
watch  | Array | List of directories to watch
coalesce_events  | Boolean | Whether events of the same nature on the same file should be coalesced in one single callback(default: false)
poll_freq  | Integer | How often events should be read for processing (default: 0)
queue_threshold  | Integer | Maximum number of events after which processing will take place (default: 0)
