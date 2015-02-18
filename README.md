# updaterepo daemon

updaterepod is a small application derived from yum and updaterepo.py (https://github.com/heroldus/updaterepo).

It relies on inotify to watch a defined set of directories for changes (RPM files) and update the repository metadata accordingly.

By design, as updaterepod is largely based on updaterepo.py, only the SQLite databases will be updated upon changes. This massively speeds things up.

## Usage
By default, the main configuration file is located at /etc/updaterepod/config.yaml.

Below, the supported options:

Option  | Type | Description
------------- | ------------- | -------------
watch  | Array | List of directories to watch
coalesce_events  | Boolean | Whether events of the same nature on the same file should be coalesced in one single callback(default: false)
poll_freq  | Integer | How often events should be read for processing (default: 0)
queue_threshold  | Integer | Maximum number of events after which processing will take place (default: 0)

## Example of usage
If you packaged and installed updaterepod via the provided RPM spec, to get it up and running should be as easy as starting up the service, either via systemd or the traditional init.d scripts.
In the following example, updaterepod has been configured to only watch one directory, that is /srv/repo/test.

```
# tail /var/log/updaterepod.log
[2015-02-18 19:32:52,489] INFO - app.Updaterepo_Daemon [updaterepod:627 set_events_coalescing()]: Disabling coalescing of events
[2015-02-18 19:32:52,490] INFO - app.Updaterepo_Daemon [updaterepod:634 start_watching()]: Start watching /srv/repo/test (wd_fd: 1)
[2015-02-18 19:32:52,490] INFO - app.Updaterepo_Daemon [updaterepod:653 run()]: Running (PID = 28654)
```

The repository is currently empty, let's add a package.
```
# yum --disablerepo=\* --enablerepo=test list available 
# cp /tmp/rpms/testrpm-1.0-1.noarch.rpm .
# tail /var/log/updaterepod.log
[2015-02-18 19:35:25,525] INFO - app.iNotifyEventHandler [updaterepod:521 process_IN_CLOSE_WRITE()]: Adding /srv/repo/test/testrpm-1.0-1.noarch.rpm
[2015-02-18 19:35:25,878] INFO - app.UpdateRepo [updaterepod:506 addRpm()]: Added testrpm-1.0-1.noarch to SQLite database
```

Clean the metadata and see if the package shows up.
```
# yum clean metadata
Cleaning repos: extra-basearch extra-i586 extra-noarch os-basearch os-i586 os-noarch test
2 metadata files removed
1 sqlite files removed
0 metadata files removed
root@installer:/opt/inst/pub/test # yum --disablerepo=\* --enablerepo=test list available 
test                                                                                                                                                         | 1.3 kB     00:00     
test/primary_db                                                                                                                                              | 2.9 kB     00:00     
Available Packages
testrpm.noarch                                                                            1.0-1                                                                             test
```

Let's remove the newly-added rpm and see if disappears as we would expect.
```
# rm -f testrpm-1.0-1.noarch.rpm 
# tail /var/log/updaterepod.log
[2015-02-18 19:36:41,879] INFO - app.iNotifyEventHandler [updaterepod:529 process_IN_DELETE()]: Removing /srv/repo/test/testrpm-1.0-1.noarch.rpm
[2015-02-18 19:36:41,894] INFO - app.UpdateRepo [updaterepod:423 execute()]: Removed testrpm-1.0-1.noarch.rpm from SQLite database
# yum clean metadata
Cleaning repos: extra-basearch extra-i586 extra-noarch os-basearch os-i586 os-noarch test
2 metadata files removed
1 sqlite files removed
0 metadata files removed
# yum --disablerepo=\* --enablerepo=test list available
test                                                                                                                                                         | 1.3 kB     00:00
test/primary_db                                                                                                                                              | 2.8 kB     00:00
```

## Contact
Matteo Cerutti - matteo.cerutti@hotmail.co.uk
