#!/usr/bin/env python
#
# Updaterepo daemon
#
# derived from:
#  - yum (http://yum.baseurl.org)
#  - updaterepo.py by Sebastian Herold (https://github.com/heroldus/updaterepo)
#
# Author: Matteo Cerutti <matteo.cerutti@hotmail.co.uk>
#

import os
import sys
import pwd
import pyinotify
import yaml
import logging
import re
from optparse import OptionParser
import signal

import shutil
from bz2 import BZ2File

# path to createrepo python modules, required
sys.path.append("/usr/share/createrepo")

import createrepo
from createrepo.yumbased import CreateRepoPackage
from createrepo import MetaDataSqlite
from yum.sqlutils import executeSQL
from createrepo.utils import MDError
from yum import misc
from yum.repoMDObject import RepoMD, RepoMDError, RepoData

try:
  import sqlite3 as sqlite
except ImportError:
  import sqlite

try:
  import sqlitecachec
except ImportError:
  pass

from createrepo.utils import _gzipOpen, bzipFile, checkAndMakeDir, GzipFile, checksum_and_rename, split_list_into_equal_chunks

class MetaDataSqlite(createrepo.MetaDataSqlite):
  # re-defining method
  def __init__(self, destdir):
    self.pri_sqlite_file = os.path.join(destdir, 'primary.sqlite')
    self.pri_cx = sqlite.Connection(self.pri_sqlite_file)
    self.file_sqlite_file = os.path.join(destdir, 'filelists.sqlite')
    self.file_cx = sqlite.Connection(self.file_sqlite_file)
    self.other_sqlite_file = os.path.join(destdir, 'other.sqlite')
    self.other_cx = sqlite.Connection(self.other_sqlite_file)
    # using 8-bit strings rather than unicode
    self.other_cx.text_factory = str
    self.primary_cursor = self.pri_cx.cursor()

    self.filelists_cursor = self.file_cx.cursor()

    self.other_cursor = self.other_cx.cursor()

    self.create_primary_db()
    self.create_filelists_db()
    self.create_other_db()

class MetaDataGenerator(createrepo.MetaDataGenerator):
  # re-defining method
  def doRepoMetadata(self):
    """wrapper to generate the repomd.xml file that stores the info
       on the other files"""

    repomd = RepoMD('repoid')
    repomd.revision = self.conf.revision

    repopath = os.path.join(self.conf.outputdir, self.conf.tempdir)
    repofilepath = os.path.join(repopath, self.conf.repomdfile)

    if self.conf.content_tags:
      repomd.tags['content'] = self.conf.content_tags
    if self.conf.distro_tags:
      repomd.tags['distro'] = self.conf.distro_tags
      # NOTE - test out the cpeid silliness here
    if self.conf.repo_tags:
      repomd.tags['repo'] = self.conf.repo_tags

    sumtype = self.conf.sumtype
    if self.conf.database_only:
      workfiles = []
      db_workfiles = [(self.md_sqlite.pri_sqlite_file, 'primary'),
              (self.md_sqlite.file_sqlite_file, 'filelists'),
              (self.md_sqlite.other_sqlite_file, 'other')]
      try:
        dbversion = str(sqlitecachec.DBVERSION)
      except AttributeError:
        dbversion = '9'
    else:
      db_workfiles = []
      workfiles = [(self.conf.otherfile, 'other',),
             (self.conf.filelistsfile, 'filelists'),
             (self.conf.primaryfile, 'primary')]

    if self.conf.deltas:
      workfiles.append((self.conf.deltafile, 'prestodelta'))

    if self.conf.database:
      if not self.conf.quiet: self.callback.log('Generating sqlite DBs')
      try:
        dbversion = str(sqlitecachec.DBVERSION)
      except AttributeError:
        dbversion = '9'
      #FIXME - in theory some sort of try/except  here
      rp = sqlitecachec.RepodataParserSqlite(repopath, repomd.repoid, None)

    for (rpm_file, ftype) in workfiles:
      complete_path = os.path.join(repopath, rpm_file)

      zfo = _gzipOpen(complete_path)
      # This is misc.checksum() done locally so we can get the size too.
      data = misc.Checksums([sumtype])
      while data.read(zfo, 2**16):
        pass
      uncsum = data.hexdigest(sumtype)
      unsize = len(data)
      zfo.close()
      csum = misc.checksum(sumtype, complete_path)
      timestamp = os.stat(complete_path)[8]

      db_csums = {}
      db_compressed_sums = {}

      if self.conf.database:
        if ftype in ['primary', 'filelists', 'other']:
          if self.conf.verbose:
            self.callback.log("Starting %s db creation: %s" % (ftype,
                                  time.ctime()))

        if ftype == 'primary':
          #FIXME - in theory some sort of try/except  here
          # TypeError appears to be raised, sometimes :(
          rp.getPrimary(complete_path, csum)

        elif ftype == 'filelists':
          #FIXME and here
          rp.getFilelists(complete_path, csum)

        elif ftype == 'other':
          #FIXME and here
          rp.getOtherdata(complete_path, csum)

        if ftype in ['primary', 'filelists', 'other']:
          tmp_result_name = '%s.xml.gz.sqlite' % ftype
          tmp_result_path = os.path.join(repopath, tmp_result_name)
          good_name = '%s.sqlite' % ftype
          resultpath = os.path.join(repopath, good_name)

          # rename from silly name to not silly name
          os.rename(tmp_result_path, resultpath)
          compressed_name = '%s.bz2' % good_name
          result_compressed = os.path.join(repopath, compressed_name)
          db_csums[ftype] = misc.checksum(sumtype, resultpath)

          # compress the files
          bzipFile(resultpath, result_compressed)
          # csum the compressed file
          db_compressed_sums[ftype] = misc.checksum(sumtype,
                               result_compressed)
          # timestamp+size the uncompressed file
          un_stat = os.stat(resultpath)
          # remove the uncompressed file
          os.unlink(resultpath)

          if self.conf.unique_md_filenames:
            csum_compressed_name = '%s-%s.bz2' % (
                       db_compressed_sums[ftype], good_name)
            csum_result_compressed =  os.path.join(repopath,
                               csum_compressed_name)
            os.rename(result_compressed, csum_result_compressed)
            result_compressed = csum_result_compressed
            compressed_name = csum_compressed_name

          # timestamp+size the compressed file
          db_stat = os.stat(result_compressed)

          # add this data as a section to the repomdxml
          db_data_type = '%s_db' % ftype
          data = RepoData()
          data.type = db_data_type
          data.location = (self.conf.baseurl, 
                os.path.join(self.conf.finaldir, compressed_name))
          data.checksum = (sumtype, db_compressed_sums[ftype])
          data.timestamp = str(db_stat.st_mtime)
          data.size = str(db_stat.st_size)
          data.opensize = str(un_stat.st_size)
          data.openchecksum = (sumtype, db_csums[ftype])
          data.dbversion = dbversion
          if self.conf.verbose:
            self.callback.log("Ending %s db creation: %s" % (ftype,
                                  time.ctime()))
          repomd.repoData[data.type] = data

      data = RepoData()
      data.type = ftype
      data.checksum = (sumtype, csum)
      data.timestamp = str(timestamp)
      data.size = str(os.stat(os.path.join(repopath, rpm_file)).st_size)
      data.opensize = str(unsize)
      data.openchecksum = (sumtype, uncsum)

      if self.conf.unique_md_filenames:
        res_file = '%s-%s.xml.gz' % (csum, ftype)
        orig_file = os.path.join(repopath, rpm_file)
        dest_file = os.path.join(repopath, res_file)
        os.rename(orig_file, dest_file)
      else:
        res_file = rpm_file
      rpm_file = res_file
      href = os.path.join(self.conf.finaldir, rpm_file)

      data.location = (self.conf.baseurl, href)
      repomd.repoData[data.type] = data

    if not self.conf.quiet and self.conf.database: self.callback.log('Sqlite DBs complete')

    for (fn, ftype) in db_workfiles:
      db_csums = {}
      db_compressed_sums = {}

      result_compressed = '%s.bz2' % fn
      compressed_name = os.path.basename(result_compressed)

      db_csums[ftype] = misc.checksum(sumtype, fn)

      bzipFile(fn, result_compressed)
      db_compressed_sums[ftype] = misc.checksum(sumtype, result_compressed)

      # timestamp+size the compressed file
      un_stat = os.stat(fn)
      db_stat = os.stat(result_compressed)

      # add this data as a section to the repomdxml
      db_data_type = '%s_db' % ftype
      data = RepoData()
      data.type = db_data_type
      data.location = (self.conf.baseurl,
            os.path.join(self.conf.finaldir, compressed_name))
      data.checksum = (sumtype, db_compressed_sums[ftype])
      data.timestamp = str(db_stat.st_mtime)
      data.size = str(db_stat.st_size)
      data.opensize = str(un_stat.st_size)
      data.openchecksum = (sumtype, db_csums[ftype])
      data.dbversion = dbversion
      repomd.repoData[data.type] = data
      try:
        os.unlink(fn)
      except (IOError, OSError), e:
        pass

    if self.conf.groupfile is not None:
      mdcontent = self._createRepoDataObject(self.conf.groupfile, 'group_gz')
      repomd.repoData[mdcontent.type] = mdcontent

      mdcontent = self._createRepoDataObject(self.conf.groupfile, 'group',
                compress=False)
      repomd.repoData[mdcontent.type] = mdcontent


    if self.conf.additional_metadata:
      for md_type, mdfile in self.conf.additional_metadata.items():
        mdcontent = self._createRepoDataObject(md_file, md_type)
        repomd.repoData[mdcontent.type] = mdcontent

    # save it down
    try:
      fo = open(repofilepath, 'w')
      fo.write(repomd.dump_xml())
      fo.close()
    except (IOError, OSError, TypeError), e:
      self.callback.errorlog(
          _('Error saving temp file for repomd.xml: %s') % repofilepath)
      self.callback.errorlog('Error was: %s') % str(e)
      fo.close()
      raise MDError, 'Could not save temp file: %s' % repofilepath

class AppendingMetaDataSqlite(MetaDataSqlite):
  def __init__(self, destdir):
    self.logger = logging.getLogger("app.AppendingMetaDataSqlite")
    MetaDataSqlite.__init__(self, destdir)

  def getPackageIndex(self):
    index = {}
    result = executeSQL(self.pri_cx, "SELECT pkgKey, location_href FROM packages;").fetchall()
    for row in result:
      index[row[1]] = row[0]
    return index

  #def containsPackage(self, po):
  #  result = executeSQL(self.pri_cx, "SELECT COUNT(*) FROM packages WHERE name = ? AND arch = ? AND version = ? AND epoch = ? AND release = ?;", (po.name, po.arch, po.version, po.epoch, po.release)).fetchall()
  #  count = result[0][0]
  #  if count > 0:
  #    return True

  #  return False

  def generateNewPackageNumber(self):
    result = executeSQL(self.pri_cx, 'SELECT MAX(pkgKey) FROM packages;').fetchall()
    maxPkgKey = result[0][0]

    if maxPkgKey is not None:
      return maxPkgKey + 1
    else:
      return 1

  def create_primary_db(self):
    self.check_or_create(self.pri_cx, 7, MetaDataSqlite.create_primary_db)

  def create_filelists_db(self):
    self.check_or_create(self.file_cx, 3, MetaDataSqlite.create_filelists_db)

  def create_other_db(self):
    self.check_or_create(self.other_cx, 3, MetaDataSqlite.create_other_db)

  def check_or_create(self, cursor, expected_count, create_method):
    result = executeSQL(cursor, 'SELECT COUNT(*) FROM sqlite_master WHERE type = "table";').fetchall()
    object_count = result[0][0]
    if object_count == 0:
      print 'Create db ...'
      create_method(self)
    elif object_count != expected_count:
      raise MDError('DB exists, but has wrong table count. Was ' + object_count.__str__() + ', expected: ' + expected_count.__str__())

  def removePkgKey(self, pkgKey):
    executeSQL(self.pri_cx, "DELETE FROM packages WHERE pkgKey = ?;", (pkgKey, ))
    self.pri_cx.commit()
    executeSQL(self.file_cx, "DELETE FROM packages WHERE pkgKey = ?;", (pkgKey, ))
    self.file_cx.commit()
    executeSQL(self.other_cx, "DELETE FROM packages WHERE pkgKey = ?;", (pkgKey, ))
    self.other_cx.commit()

def uncompressDB(from_file, to_file):
  if os.path.exists(from_file):
    orig = BZ2File(from_file)
    dest = open(to_file, 'wb')
    try: 
      shutil.copyfileobj(orig, dest)
    finally:
      dest.close()
      orig.close()
  else:
    print "DB skipped: File not found " + from_file

def uncompressDBs(from_dir, to_dir):
  uncompressDB(os.path.join(from_dir, 'primary.sqlite.bz2'), os.path.join(to_dir, 'primary.sqlite'))
  uncompressDB(os.path.join(from_dir, 'other.sqlite.bz2'), os.path.join(to_dir, 'other.sqlite'))
  uncompressDB(os.path.join(from_dir, 'filelists.sqlite.bz2'), os.path.join(to_dir, 'filelists.sqlite'))

def _return_primary_files(self, list_of_files=None):
  returns = {}
  if list_of_files is None:
    list_of_files = self.returnFileEntries('file')
  for item in list_of_files:
    if item is None:
      continue
    if misc.re_primary_filename(item):
      returns[item] = 1
  return returns.keys()

def _return_primary_dirs(self):
  returns = {}
  for item in self.returnFileEntries('dir'):
    if item is None:
      continue
    if misc.re_primary_dirname(item):
      returns[item] = 1
  return returns.keys()

# set missing functions
CreateRepoPackage._return_primary_files = _return_primary_files
CreateRepoPackage._return_primary_dirs = _return_primary_dirs

class UpdateRepo(object):
  def __init__(self, config):
    self.logger = logging.getLogger("app.UpdateRepo")
    self.config = config

    if os.path.isabs(self.config.directory):
      self.config.basedir = os.path.dirname(self.config.directory)
      self.config.relative_dir = os.path.basename(self.config.directory)
    else:
      self.config.basedir = os.path.realpath(self.config.basedir)
      self.config.relative_dir = self.config.directory

    if not self.config.directory.endswith('/'):
      self.config.directory = self.config.directory + '/'

    self.config.database_only = True

    if not self.config.outputdir:
      self.config.outputdir = os.path.join(self.config.basedir, self.config.relative_dir)

    self.output_dir = os.path.join(self.config.outputdir, 'repodata')
    self.temp_dir = os.path.join(self.config.outputdir, '.repodata')

  def execute(self, **kargs):
    if not 'action' in kargs:
      raise(ValueError, "Must specify action to %s" % self.__class__.__name__)

    self.reuseExistingMetadata()
    self.generator = MetaDataGenerator(self.config)
    self.generator.md_sqlite = AppendingMetaDataSqlite(self.temp_dir)
    self.nextPkgKey = self.generator.md_sqlite.generateNewPackageNumber()

    packagesInDb = self.generator.md_sqlite.getPackageIndex()
    packagesInDbKeys = set(packagesInDb.keys())

    if kargs['action'] == "remove":
      for package in self.config.packages:
        if package in packagesInDb:
          pkgKey = packagesInDb[package]
          self.generator.md_sqlite.removePkgKey(pkgKey)
          self.logger.info("Removed %s from SQLite database" % package)
        else:
          self.logger.info("Package %s is already absent" % package)
    elif kargs['action'] == "add":
      for package in self.config.packages:
        remove_existing = False
        if package in packagesInDb:
          # FIXME: ideally, we would check if the package actually differs 
          self.logger.info("Package %s is already present. The existing one will be removed." % package)
          remove_existing = True

        try:
          self.addRpm(package)
        except Exception, e:
          self.logger.error("Error adding %s to SQLite database: %s" % (package, e))

        if remove_existing:
          pkgKey = packagesInDb[package]
          self.generator.md_sqlite.removePkgKey(pkgKey)
    else:
      if self.config.packages is None:
        self.config.packages = set(self.listRpms())

      packagesToDelete = list(packagesInDbKeys - self.config.packages)
      packagesToAdd = list(self.config.packages - packagesInDbKeys)

      self.logger.debug("DB Packages: %s " % packagesInDbKeys.__str__())
      self.logger.debug("Packages: %s " % self.config.packages.__str__())
      self.logger.debug("Delete: %s " % packagesToDelete.__str__())
      self.logger.debug("Add: %s " % packagesToAdd.__str__())

      for package in packagesToDelete:
        pkgKey = packagesInDb[package]
        try:
          self.generator.md_sqlite.removePkgKey(pkgKey)
          self.logger.info("Removed %s from SQLite database" % package)
        except Exception, e:
          self.logger.error("Error removing %s from SQLite database: %s" % (package, e))

      for package in packagesToAdd:
        try:
          self.addRpm(package)
        except Exception, e:
          self.logger.error("Error adding %s to SQLite database: %s" % (package, e))

    self.generateMetaData()

  def listRpms(self):
    dirLength = len(self.config.directory)
    rpms = []
    for root, dirnames, files in os.walk(self.config.directory):
      relpath = root[dirLength:]
      for name in files:
        if name.endswith('.rpm'):
          rpms.append(os.path.join(relpath, name))

    return rpms

  def reuseExistingMetadata(self):
    if os.path.exists(self.temp_dir):
      shutil.rmtree(self.temp_dir)
    os.mkdir(self.temp_dir)

    uncompressDBs(self.output_dir, self.temp_dir)

  def generateMetaData(self):
    self.generator.closeMetadataDocs()
    self.generator.doRepoMetadata()
    self.generator.doFinalMove()

  def addRpm(self, rpm):
    po = self.generator.read_in_package(rpm, self.config.directory)

    #if self.generator.md_sqlite.containsPackage(po):
    #  self.logger.info("Package %s already present in SQLite database" % po.__str__())
    #else:
    po.crp_reldir = self.config.directory
    po.crp_packagenumber = self.nextPkgKey
    self.nextPkgKey += 1
    po.crp_baseurl = self.config.baseurl

    po.do_sqlite_dump(self.generator.md_sqlite)

    self.logger.info("Added %s to SQLite database" % po.__str__())

class iNotifyEventHandler(pyinotify.ProcessEvent):
  def __call__(self, event):
    filename = os.path.basename(event.pathname)
    if not re.search('^\.', filename):
      if filename.endswith('.rpm'):
        super(iNotifyEventHandler, self).__call__(event)

  def __init__(self):
    self.logger = logging.getLogger("app.iNotifyEventHandler")
    self.config = createrepo.MetaDataConfig()
    self.config.quiet = True

  def process_IN_CLOSE_WRITE(self, event):
    self.logger.info("Adding %s" % event.pathname)

    self.config.directory = os.path.dirname(event.pathname)
    self.config.packages = [os.path.basename(event.pathname)]

    UpdateRepo(self.config).execute(action="add")

  def process_IN_DELETE(self, event):
    self.logger.info("Removing %s" % event.pathname)

    self.config.directory = os.path.dirname(event.pathname)
    self.config.packages = [os.path.basename(event.pathname)]

    UpdateRepo(self.config).execute(action="remove")

class Updaterepo_Daemon:
  def __init__(self, **kwargs):
    # set up logger for this instance
    self.logger = logging.getLogger("app.Updaterepo_Daemon")

    # read configuration file
    self.pid_file = kwargs['pid_file']
    self.config_file = kwargs['config_file']

    self.config = None
    self.read_config()

    # dictionary containing path to WatchManager file descriptor association
    self.wd_fds = {}

    # watchmanager object
    self.wm = pyinotify.WatchManager()

    # eventhandler object
    handler = iNotifyEventHandler()

    # notifier object
    self.notifier = pyinotify.Notifier(self.wm, handler, read_freq=self.config['poll_freq'], threshold=self.config['queue_threshold'])

    # enable coalescing of events so that only one event will be generated for multiple actions on the same file
    self.set_events_coalescing()

    # handling signals
    signal.signal(signal.SIGHUP, self.signal_handler)
    signal.signal(signal.SIGTERM, self.signal_handler)

  def read_config(self):
    try:
      config = yaml.load(open(self.config_file, 'r'))
    except Exception, e:
      logger.error("Failed to load %s configuration file: %s" % (self.config_file, e))
      sys.exit(1)

    if ('watch' not in config) or (config['watch'] is None) or (len(config['watch']) == 0):
      logger.error("Must specify at least one directory to watch")
      sys.exit(1)

    if ('coalesce_events' not in config) or (config['coalesce_events'] is None):
      config['coalesce_events'] = False

    if ('poll_freq' not in config) or (config['poll_freq'] is None):
      config['poll_freq'] = 0

    if ('queue_threshold' not in config) or (config['queue_threshold'] is None):
      config['queue_threshold'] = 0

    self.config = config

  def reload_config(self):
    old_config = self.config.copy()

    self.read_config()

    for path in old_config['watch']:
      if path not in self.config['watch']:
        self.stop_watching(path)

    for path in self.config['watch']:
      if path not in old_config['watch']:
        self.start_watching(path)

    if old_config['coalesce_events'] != self.config['coalesce_events']:
      if old_config['coalesce_events']:
        self.set_events_coalescing(False)
      else:
        self.set_events_coalescing(True)

  def signal_handler(self, signum, frame):
    self.logger.debug("Received signal: %s at frame: %s" % (signum, frame))

    if signum == signal.SIGTERM:
      if os.path.isfile(self.pid_file):
        os.remove(self.pid_file)
      self.logger.info("Requested daemon shutdown ..")
      sys.exit(0)
    elif signum == signal.SIGHUP:
      self.logger.info("Requested configuration reload ..")
      self.reload_config()

  def set_events_coalescing(self, value = None):
    if value is None:
      value = self.config['coalesce_events']

    if value == True:
      self.logger.info("Enabling coalescing of events")
    else:
      self.logger.info("Disabling coalescing of events")

    self.notifier.coalesce_events(value)

  def start_watching(self, path):
    fd = self.wm.add_watch(path, pyinotify.IN_CLOSE_WRITE | pyinotify.IN_DELETE, rec=False)
    wd_fd = fd.itervalues().next()
    self.logger.info("Start watching %s (wd_fd: %d)" % (path, wd_fd))
    self.wd_fds[path] = wd_fd

  def stop_watching(self, path):
    wd_fd = self.wd_fds[path]
    self.logger.info("Stop watching %s (wd_fd: %d)" % (path, wd_fd))
    self.wm.del_watch(wd_fd)
    del(self.wd_fds[path])

  def run(self):
    try:
      pid = os.getpid()
      file(self.pid_file, 'w').write(str(pid))
    except Exception, e:
      self.logger.error("Failed to write PID file: %s" % e)
      sys.exit(1)

    for path in self.config['watch']:
      self.start_watching(path)
    self.logger.info("Running (PID = %d)" % pid)
    self.notifier.loop()

def parse_args():
  parser = OptionParser(usage = "Usage: %prog [options]")
  parser.add_option('-c', '--config', dest = "config_file", default = "/etc/updaterepod/config.yaml", help = "Path to configuration file", metavar = "FILE")
  parser.add_option('-d', '--debug', action = "store_false", dest = "debug", default = False, help = "Enable debug mode")
  parser.add_option('-l', '--logdest', dest = "logdest", default = None, help = "Optional destination log file")
  parser.add_option('-u', '--user', dest = "user", default = None, help = "Optional user to run with")
  parser.add_option('-p', '--pid', dest = "pid_file", default = None, help = "PID file")

  return parser.parse_args()

def main():
  options, args = parse_args()

  if options.user is not None:
    try:
      uid = pwd.getpwnam(options.user)
    except Exception, e:
      sys.stderr.write("Failed to look UID for user %s: %s" % (options.user, e))
      sys.exit(1)
 
    try:
      os.setuid(uid.pw_uid)
    except Exception, e:
      sys.stderr.write("Failed to call setuid: %s" % e)
      sys.exit(1)

  logger = logging.getLogger("app")
  if options.logdest is not None:
    handler = logging.FileHandler(options.logdest)
  else:
    handler = logging.StreamHandler()
  formatter = logging.Formatter("[%(asctime)s] %(levelname)s - %(name)s [%(filename)s:%(lineno)s %(funcName)s()]: %(message)s")
  handler.setFormatter(formatter)
  logger.addHandler(handler)

  if options.debug:
    logger.setLevel(logging.DEBUG)
  else:
    logger.setLevel(logging.INFO)

  updaterepod = Updaterepo_Daemon(config_file=options.config_file, pid_file=options.pid_file)
  updaterepod.run()

if __name__ == "__main__":
  sys.exit(main())
