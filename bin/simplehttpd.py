#!/usr/bin/python
# Copyright (c) 2012 Liraz Siri <liraz@turnkeylinux.org>

"""
Simple HTTP server

Options:

    --runas=username
    --daemonize=/path/to/pidfile
    --logfile=/path/to/logfile

"""
import os
from os.path import exists, abspath

import sys
import getopt

import SimpleHTTPServer
import SocketServer
import select
import ssl

import pwd
import grp
import temp

import signal

class Error(Exception):
    pass

def fatal(e):
    print >> sys.stderr, "error: " + str(e)
    sys.exit(1)

def usage(e=None):
    print >> sys.stderr, "Error: " + str(e)
    print >> sys.stderr, "Syntax: %s [ -options ] path/to/webroot [address:]http-port [ [ssl-address:]ssl-port path/to/pem [ path/to/key ] ]" % sys.argv[0]
    print >> sys.stderr, __doc__.strip()
    sys.exit(1)

class ServerAddress:

    @staticmethod
    def parse_address(address):
        if ':' in address:
            host, port = address.split(':', 1)
        else:
            host = '0.0.0.0'
            port = address

        try:
            port = int(port)
            if not 0 < port < 65535:
                raise Exception
        except:
            raise Error("illegal port")

        return host, port

    def __init__(self, address):

        host, port = self.parse_address(address)
        self.host = host
        self.port = port

class HTTPSConf(ServerAddress):
    def __init__(self, address, certfile, keyfile=None):
        ServerAddress.__init__(self, address)
        if keyfile is None:
            keyfile = certfile

        self.certfile = self._validate_path(certfile)
        self.keyfile = self._validate_path(keyfile)

    @staticmethod
    def _validate_path(fpath):
        if not exists(fpath):
            raise Error("no such file '%s'" % fpath)
        return abspath(fpath)

    CIPHERS='ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES256-GCM-SHA384:DHE-RSA-AES128-GCM-SHA256:DHE-DSS-AES128-GCM-SHA256:kEDH+AESGCM:ECDHE-RSA-AES128-SHA256:ECDHE-ECDSA-AES128-SHA256:ECDHE-RSA-AES128-SHA:ECDHE-ECDSA-AES128-SHA:ECDHE-RSA-AES256-SHA384:ECDHE-ECDSA-AES256-SHA384:ECDHE-RSA-AES256-SHA:ECDHE-ECDSA-AES256-SHA:DHE-RSA-AES128-SHA256:DHE-RSA-AES128-SHA:DHE-DSS-AES128-SHA256:DHE-RSA-AES256-SHA256:DHE-DSS-AES256-SHA:DHE-RSA-AES256-SHA:AES128-GCM-SHA256:AES256-GCM-SHA384:AES128-SHA256:AES256-SHA256:AES128-SHA:AES256-SHA:AES:CAMELLIA:DES-CBC3-SHA:!aNULL:!eNULL:!EXPORT:!DES:!RC4:!MD5:!PSK:!aECDH:!EDH-DSS-DES-CBC3-SHA:!EDH-RSA-DES-CBC3-SHA:!KRB5-DES-CBC3-SHA'

def serve_forever(server1,server2):
    while True:
        r, w, e = select.select([server1,server2],[],[],0)
        if server1 in r:
            server1.handle_request()
        if server2 in r:
            server2.handle_request()

def is_writeable(path):
    if not os.path.exists(path):
        path = os.path.dirname(path)

    return os.access(path, os.W_OK)

def daemonize(pidfile, logfile=None):
    if logfile is None:
        logfile = "/dev/null"

    pid = os.fork()
    if pid != 0:
        print >> file(pidfile, "w"), "%d" % pid
        sys.exit(1)

    os.chdir("/")
    os.setsid()

    logfile = file(logfile, "w")
    os.dup2(logfile.fileno(), sys.stdout.fileno())
    os.dup2(logfile.fileno(), sys.stderr.fileno())

    devnull = file("/dev/null", "r")
    os.dup2(devnull.fileno(), sys.stdin.fileno())

def drop_privileges(user):
    pwent = pwd.getpwnam(user)
    uid, gid, home = pwent[2], pwent[3], pwent[5]
    os.unsetenv("XAUTHORITY")
    os.putenv("USER", user)
    os.putenv("HOME", home)

    usergroups = []
    groups = grp.getgrall()
    for group in groups:
        if user in group[3]:
            usergroups.append(group[2])

    os.setgroups(usergroups)
    os.setgid(gid)
    os.setuid(uid)

class TempOwnedAs(str):
    def __new__(cls, fpath, owner, chmod=0600):

        if not exists(fpath):
            raise Error("file does not exist '%s'" % fpath)

        tempfile = temp.TempFile()

        tempfile.write(file(fpath).read())
        tempfile.close()

        pwent = pwd.getpwnam(owner)

        os.chown(tempfile.path, pwent.pw_uid, pwent.pw_gid)
        if chmod:
            os.chmod(tempfile.path, chmod)

        self = str.__new__(cls, tempfile.path)
        self.tempfile = tempfile

        return self

def simplewebserver(webroot, http_address=None, https_conf=None, runas=None):

    httpd = SocketServer.TCPServer((http_address.host, http_address.port),
                                   SimpleHTTPServer.SimpleHTTPRequestHandler) \
            if http_address else None

    httpsd = None
    if https_conf:

        certfile = https_conf.certfile
        keyfile = https_conf.keyfile

        if runas:
            certfile = TempOwnedAs(certfile, runas)
            keyfile = TempOwnedAs(keyfile, runas)

        httpsd = SocketServer.TCPServer((https_conf.host, https_conf.port),
                                        SimpleHTTPServer.SimpleHTTPRequestHandler)

        httpsd.socket = ssl.wrap_socket(httpsd.socket, certfile=certfile, keyfile=keyfile,
                                        server_side=True, ssl_version=ssl.PROTOCOL_TLSv1,
                                        ciphers=https_conf.CIPHERS)

    orig_cwd = os.getcwd()
    os.chdir(abspath(webroot))

    if runas:
        drop_privileges(runas)

    if httpsd and httpd:
        serve_forever(httpd, httpsd)
    elif httpd:
        httpd.serve_forever()
    elif httpsd:
        httpsd.serve_forever()

    os.chdir(orig_cwd)

def main():
    args = sys.argv[1:]
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], 'h', ["daemonize=", "logfile=", "runas="])
    except getopt.GetoptError, e:
        usage(e)

    daemonize_pidfile = None
    logfile = None
    runas = None

    for opt, val in opts:
        if opt == '-h':
            usage()

        if opt == '--daemonize':
            daemonize_pidfile = abspath(val)

        if opt == '--logfile':
            logfile = abspath(val)

        if opt == '--runas':
            try:
                pwd.getpwnam(val)
            except KeyError:
                fatal("no such user '%s'" % val)

            runas = val

    if not args:
        usage()

    if len(args) not in (2, 4, 5):
        usage("incorrect number of arguments")

    if daemonize_pidfile and not is_writeable(daemonize_pidfile):
        fatal("pidfile '%s' not writeable" % daemonize_pidfile)

    if logfile:
        if not daemonize_pidfile:
            fatal("--logfile can only be used with --daemonize")

        if not is_writeable(logfile):
            fatal("logfile '%s' not writeable" % logfile)

    webroot, http_address = args[:2]

    if http_address in ("", "0"):
        http_address = None
    else:
        http_address = ServerAddress(http_address)

    https_conf = None
    if len(args[2:]):
        address, certfile = args[2:4]

        try:
            keyfile = args[4]
        except IndexError:
            keyfile = None

        https_conf = HTTPSConf(address, certfile, keyfile)

    if daemonize_pidfile:
        daemonize(daemonize_pidfile, logfile)

    def handler(signum, stack):
        print "caught signal (%d), exiting" % signum
        sys.exit(1)
    signal.signal(signal.SIGTERM, handler)

    simplewebserver(webroot, http_address, https_conf, runas)

if __name__ == "__main__":
    main()
