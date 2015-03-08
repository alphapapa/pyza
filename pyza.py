#!/usr/bin/env python

# Based on MixZaTape

import argparse
import logging as log
import os
import random
import re
import requests
import subprocess
import sys
import tempfile
import time

class Songza(object):
    SONGZA_URL_PREFIX = 'https://songza.com'
    REQUEST_HEADERS = {"Content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                       "Accept": "application/json, text/javascript, */*; q=0.01",
                       "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X"
                       + "10_8_3) AppleWebKit/537.36 (KHTML, like Gecko)"
                       + "Chrome/27.0.1453.93 Safari/537.36"}

    @staticmethod
    def request(path, params=None, method='get'):
        '''Returns a requests result for a request.'''

        url = Songza.SONGZA_URL_PREFIX + path

        return getattr(requests, method)(url, params=params, headers=Songza.REQUEST_HEADERS)

    @staticmethod
    def findStations(query):
        '''Returns list of Station objects for query string.'''

        r = Songza.request("/api/1/search/station", params={'query': query})

        stations = [Station(str(station['id']),
                            station['name'],
                            station['song_count'],
                            station['description'])
                    for station in r.json()]

        log.debug('Found %s stations for query "%s": %s',
                  len(stations), query, [station for station in stations])

        return stations

class Track(object):
    def __init__(self, url, data):
        self.url = url
        self.album = data['album'].encode('utf8')
        self.title = data['title'].encode('utf8')
        self.artist = data['artist']['name'].encode('utf8')
        self.duration = data['duration']
        self.genre = data['genre'].encode('utf8')
        self.id = data['id']

        self.file = None

    def __repr__(self):
        return self._reprstr()

    def __str__(self):
        return self._reprstr()

    def _reprstr(self):
        return '%s - "%s" from "%s" (%s)' % (self.artist, self.title, self.album, self.genre)

    def download(self):
        '''Downloads the song to a temp file.'''

        # This is unnecessary right now, since VLC can handle
        # downloading the files itself, and handles deleting them

        self.file = tempfile.NamedTemporaryFile(mode='w+b')

    # TODO: Use __del__?
    def delete(self):
        '''Deletes the downloaded file.'''
        self.file.close()

class Station(object):
    def __init__(self, stationID, name=None, songCount=None, description=None):
        self.id = stationID
        self.name = name.encode('utf8') if name else None
        self.songCount = songCount
        self.description = description.encode('utf8') if description else None

        self.previousTrack = None
        self.track = None
        self.nextTrack = None
        self.trackStartTime = None

        self.path = "/api/1/station/" + self.id

        # TODO: Get station name/songcount if not set
        if not self.name or not self.songCount:
            self._getDetails()

    def _getDetails(self):
        '''Gets song details and sets name, songCount, and description
        attributes.'''

        r = Songza.request(self.path).json()
        self.name = r['name'].encode('utf8')
        self.songCount = r['song_count']
        self.description = r['description'].encode('utf8')

    def __eq__(self, other):
        return self.id == other.id

    def __hash__(self):
        return int(self.id)

    def __repr__(self):
        return '%s: %s (%s songs)' % (self.id, self.name, self.songCount)

    def __str__(self):
        return '%s: %s (%s songs): %s' % (self.id, self.name,
                                          self.songCount, self.description)

    def next(self):
        '''Set the station's current track to the next track and returns next track.'''

        params = {"cover_size": "m", "format": "aac", "buffer": 0}
        result = Songza.request(self.path + '/next', params=params, method='post').json()

        self.previousTrack = self.track if self.track else None
        self.track = Track(result['listen_url'], result['song'])

        log.debug('New track for station %s (%s): %s: %s',
                  self.name, self.id, self.track.artist, self.track.title)

        return self.track

    def _vote(self, direction):
        result = Songza.request("/api/1/station/%s/song/%s/vote/%s"
                                % (self.id, self.track.id, direction),
                                method='post')

        log.debug(result)

    def downVote(self):
        self._vote('down')

    def upVote(self):
        self._vote('up')


# TODO: Clean up this class
class VlcPlayer:

    def __init__(self, debug=False):
        self.process = None

        # is_paused
        # =========
        # True if playback is currently paused
        self.is_paused = False

        self.time = 0

        self.debug = debug

        # regex used to parse VLC STDOUT for time remaining
        # sometimes we get extra prompt characters that need to be trimmed
        self.time_remaining_regex = r"[> ]*(\d*)\r\n"

        # setup logger
        # clear log on startup
        logpath = "./.player.log"
        if os.path.exists(logpath):
            os.remove(logpath)

        if self.debug:
            self.logger = logging.getLogger("player")
            handler = logging.FileHandler(logpath)
            formatter = logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.DEBUG)

    # def __del__(self):
        # self.process.close()

    # send_command(command)
    # =====================
    # Sends the specified command to the player
    def send_command(self, command):
        if self.process is not None:
            self.process.stdin.write(command.encode("utf-8"))

    # send_command_readline(command)
    # ==============================
    # Sends the specified command to the player, and returns on line of
    # response from STDOUT
    def send_command_readline(self, command):
        if self.process is not None:
            self.process.stdin.write(command.encode("utf-8"))

            # make sure to forward to the end
            return self.process.stdout.readline()

        return None

    # is_open()
    # =========
    # Returns true if the player is currently open.
    def is_open(self):
        return bool(self.process)

    # volume_up()
    # ===========
    # Raises the volume.
    def volume_up(self):
        self.send_command_readline("volup\n")

    # volume_down()
    # ============
    # Lowers the volume.
    def volume_down(self):
        self.send_command_readline("voldown\n")

    # pause()
    # =======
    # Pauses playback.
    def pause(self):
        self.is_paused = not self.is_paused
        self.send_command("pause\n")

    # stop()
    # ======
    # Stops all playback, shutting down the player.
    def stop(self):
        self.send_command("shutdown\n")
        self.process = None

    # enqueue(file)
    # =============
    # Adds a file to queue.
    def enqueue(self, file):
        self.send_command("enqueue " + file + "\n")

    # skip()
    # ======
    # Skips the current track
    def skip(self):
        self.send_command("next\n")
        self.time = 0

    # seek(seconds)
    # =============
    # Skips the current track
    def seek(self, seconds):
        self.send_command("seek {0}\n".format(seconds))
        # update time value
        # self.time += seconds

    # get_time()
    # ==========
    # Gets the running time in for the current track.
    def get_time(self):
        try:
            # buffer the current time value
            self.time = int(self.send_command_readline("get_time\n")[2:])
        finally:
            # Sometimes when seeking, VLC is slow to respond, and the STDOUT output
            # gets out of sync. In this case, return the last know time value.
            return self.time

    # play(file)
    # ==========
    # Plays the file with the specified name.
    def play(self, file):
        # print "filename: " + file

        # if already playing, add the next file to the queue
        if self.is_open():
            # print "is open"
            self.enqueue(file)
            self.skip()
        else:
            self.process = subprocess.Popen(["vlc", "-Irc", "--quiet", file],
                                            shell=False,
                                            stdout=subprocess.PIPE,
                                            stdin=subprocess.PIPE,
                                            stderr=subprocess.STDOUT)

            self.process.stdout.readline()
            self.process.stdout.readline()

    # time_remaining()
    # ================
    # The amount of time remaining on the current track.
    def time_remaining(self):
        timeRemaining = None

        if (self.is_open()):
            try:

                # use regex to chop off leading chars
                # attempt to read duration of track
                response_text = self.send_command_readline("get_length\n")
                match_dur = re.search(self.time_remaining_regex, response_text)

                if match_dur:
                    duration = int(match_dur.group(1))
                else:
                    self.logger.debug(
                        "unable to parse time remaining text: {0}", response_text)

                # attempt to read current time elasped
                response_text = self.send_command_readline("get_time\n")
                match_rem = re.search(self.time_remaining_regex, response_text)

                if match_rem:
                    remaining = int(match_rem.group(1))
                else:
                    self.logger.debug(
                        "unable to parse time remaining text: {0}", response_text)

                # duration = int(self.send_command_readline("get_length\n")[2:])
                # remaining = int(self.send_command_readline("get_time\n")[2:])

                if match_dur and match_rem:
                    timeRemaining = duration - remaining

            except Exception, ex:
                log.error("error: " + str(ex))

        return timeRemaining


class Player(object):
    def __init__(self):
        self.station = None
        self.track = None

        self.paused = False
        self.playing = False
        self.stopped = True

        self.position = None

        self.random = False
        self.stations = None

        self.outputURLs = False

        self.nextTrack = None

    def _getNextTrack(self):
        '''Sets the station depending on random mode, then sets the next
        track.'''

        if self.random:
            self.station = random.choice(self.stations)
            log.info('Next station: %s', self.station)

        self.nextTrack = self.station.next()

        log.debug('Next track: %s', self.nextTrack)

    def next(self):
        '''Calls subclass's _next() method to play the next track.'''

        # Rather than redefine the child class's next() method, I call
        # a private method so that it's obvious that a child class
        # must define _next().  Otherwise it wouldn't be obvious that
        # a child class would have to redefine next().  I think this
        # makes sense...

        # TODO: Use the @abc.abstractmethod decorator as explained
        # here: https://julien.danjou.info/blog/2013/guide-python-static-class-abstract-methods
        # Or will that work, since I use log.info here?
        self._next()

        log.info("Playing track: %s", self.track)

    def play(self):
        '''Starts playing the station or stations.'''

        # Get and play the next track
        self.next()

        self.paused = False
        self.playing = True
        self.stopped = False


class MPD(Player):
    DEFAULT_PORT = 6600

    def __init__(self, host, port=DEFAULT_PORT, password=None):
        self.host = host
        self.port = port
        self.password = password

        # Import python-mpd2.  This might not be the "correct" way to
        # do this, putting the import down here, but this way people
        # can use the script without having python-mpd2.
        import mpd
        if mpd.VERSION < (0, 5, 4):
            log.critical('Using MPD requires python-mpd >= 0.5.4 (aka python-mpd2).')
            raise Exception

        super(MPD, self).__init__()

        self.mpd = mpd.MPDClient()

        self.mpd.connect(self.host, self.port)

        self.nextSongID = None  # Song ID number

        self._getPlaylist()
        self._status()

    def _checkConnection(self):
        '''Pings the server and reconnects if necessary.'''

        # I don't know why the connection tends to get dropped, but it
        # does.  This takes care of it.
        try:
            self.mpd.ping()
        except:
            log.debug("Connection lost to server: %s.  Reconnecting...",
                      self.host)

            try:
                self.mpd.connect(self.host, self.port)
            except:
                log.critical("Couldn't reconnect to server: %s",
                             self.host)
                raise Exception
            else:
                log.debug("Reconnected to server: %s", self.host)

    def _getNextTrack(self):
        '''Gets next track from Player, then adds to MPD playlist and sets
        self.nextSongID.'''

        super(MPD, self)._getNextTrack()

        self.nextSongID = self._add(self.nextTrack)

    def _next(self):
        '''Gets the next track from the current station and then plays it.'''

        # When the playlist is empty (first time), get the first track
        if self.nextTrack is None:
            self._getNextTrack()

        # Play the next song if it's not already playing; otherwise
        # MPD probably skipped to the next track
        if self.songID != self.nextSongID:
            self._play(self.nextSongID)

        # Set the player's track object to the track now playing
        self.track = self.nextTrack

        # Get the next track and add it to the playlist
        self._getNextTrack()

    def _getPlaylist(self):
        '''Gets playlist from server and sets self.playlist.'''

        self._checkConnection()

        self.playlist = self.mpd.playlist()

    def _add(self, track):
        '''Adds track to playlist and returns new track's songID.'''

        self._checkConnection()

        songID = int(self.mpd.addid(track.url))

        # TODO: Figure out why sometimes the tags don't seem to get
        # added, even though there are no errors
        self.mpd.addtagid(songID, 'artist', track.artist)
        self.mpd.addtagid(songID, 'album', track.album)
        self.mpd.addtagid(songID, 'title', track.title)
        self.mpd.addtagid(songID, 'genre', track.genre)

        # TODO: Figure out a way to set the track's duration in MPD.
        # As it is now, MPD gets the duration from the file by itself,
        # but then it doesn't update the duration in the playlist, so
        # the playlist shows "0:00" for it.  MPD doesn't let you set
        # the duration for a song with the addtagid command.  Maybe
        # this could be considered a bug in MPD, that it doesn't
        # update the duration in the playlist after it finds it out,
        # because MPD does display the duration in the current status
        # info, just not in the playlist.

        return songID

    def _play(self, songID):
        '''Plays songID.'''

        self._checkConnection()

        self.mpd.playid(songID)
        self.songID = songID

    def _status(self):
        '''Gets status of MPD server and updates attributes.'''

        self._checkConnection()

        self.currentStatus = self.mpd.status()

        self.playing = True if self.currentStatus['state'] == 'play' else False
        self.paused = True if self.currentStatus['state'] == 'pause' else False

        self.songID = int(self.currentStatus['songid']) if 'songid' in self.currentStatus else None
        self.position = self.currentStatus['elapsed'] if 'elapsed' in self.currentStatus else None

    def play(self):
        '''Calls parent play() method to set the current station, then
        monitors MPD and adds the next track when necessary.'''

        super(MPD, self).play()
        lastSongID = self.songID

        while True:

            # 3 seconds seems reasonable to start with.  Since
            # status() causes debug output, doing it every second
            # results in a LOT of debug output.
            time.sleep(3)

            self._status()

            # Add the next song when the current song changes
            if lastSongID != self.songID:
                log.debug('Song changed.  Last song:%s  Current song:%s',
                          lastSongID, self.songID)

                self.next()
                lastSongID = self.songID

class VLC(Player):
    def __init__(self):
        super(VLC, self).__init__()

        self.player = VlcPlayer()

        log.debug("Initialized VLC Player.")

    def _next(self):
        '''Gets next track and plays it.'''

        self._getNextTrack()
        self.track = self.nextTrack
        self.player.play(self.track.url)

    def _status(self):
        '''Updates player status and position.'''

        # In this future this may be used to let VLC skip tracks.
        # Right now it's unused.

        self.position = self.player.get_time()

    def play(self):
        '''Calls parent play() method, then loops, sleeping for the track's
        duration and then starting the next track.'''

        super(VLC, self).play()

        # Loop
        while True:

            if not self.track.duration:
                log.critical('Duration not available for track: %s.  This should not happen.',
                             self.track)
                raise Exception

            sleepTime = self.track.duration

            log.debug('Sleeping for %s seconds', sleepTime)

            # Wait for the track to finish playing
            time.sleep(float(sleepTime))

            self.next()


def printStations(stations):
    # Print list of stations
    print '%s stations found:' % len(stations)
    for station in stations:
        print station

def main():

    # Parse args
    parser = argparse.ArgumentParser(description='A terminal-based Songza client.  Plays with VLC by default.')
    parser.add_argument('-e', '--exclude', nargs='*', metavar='STRING',
                        help="Exclude stations matching strings")
    parser.add_argument('-f', '--find', nargs='*', metavar='STRING',
                        help="List stations matching strings")
    parser.add_argument('-n', '--names-only', action='store_true',
                        dest='namesOnly',
                        help="Only search station names, not station descriptions or other data")
    parser.add_argument('-m', '--mpd', nargs='?', metavar='HOST[:PORT]',
                        const='localhost:6600',
                        help="Play with MPD server.  Default: localhost:6600")
    parser.add_argument('-r', '--random', nargs='*', metavar='STRING',
                        help="Play one random station matching string")
    parser.add_argument('-R', '--random-stations', nargs='*', metavar='STRING',
                        dest='randomStations',
                        help="Play one song each from random stations matching strings")
    parser.add_argument('-s', '--station', nargs='*', metavar='STATION',
                        help="A station name, partial station name, or station ID number")
    parser.add_argument('--sort', dest='sort', choices=['name', 'songs', 'id'],
                        default='songs',
                        help="Sort station list.  Default: number of songs")
    parser.add_argument("-v", "--verbose", action="count", dest="verbose", help="Be verbose, up to -vv")
    args = parser.parse_args()

    # Setup logging
    if args.verbose == 1:
        LOG_LEVEL = log.INFO
    elif args.verbose >=2:
        LOG_LEVEL = log.DEBUG
    else:
        LOG_LEVEL = log.WARNING
    log.basicConfig(level=LOG_LEVEL, format="%(levelname)s: %(message)s")

    log.debug("Args: %s", args)

    # Check args
    if not (args.find or args.station or args.random or args.randomStations):
        log.error('Please provide a station or search string.')
        parser.print_help()
        return False

    if args.find and args.station:
        log.error('Please use either -f or -s but not both.')
        return False

    if args.random and args.randomStations:
        log.error('Please use either -r or -R but not both.')
        return False

    # Handle player arg
    if args.mpd:
        # Play with MPD

        if len(args.mpd) > 0:
            # Get host and port if given
            if ':' in args.mpd:
                host, port = args.mpd.split(':')
            else:
                host = args.mpd
                port = MPD.DEFAULT_PORT
        else:
            # Use defaults
            host = 'localhost'
            port = MPD.DEFAULT_PORT

        try:
            player = MPD(host, port)
        except Exception as e:
            log.critical("Couldn't connect to MPD server: %s:%s: %s", host, port, e)
            return False
        else:
            log.debug('Connected to MPD server: %s', host)

    else:
        # Play with VLC
        try:
            player = VLC()
        except Exception as e:
            log.critical("Couldn't launch VLC: %s", e)
            return False

    # Handle sort arg
    sortReverse = False
    if args.sort:
        if args.sort == 'songs':
            sortBy = 'songCount'
        elif args.sort == 'id':
            sortBy = 'id'
            sortReverse = True
        else:
            sortBy = 'name'

    # Handle args
    if args.station or args.find or args.random or args.randomStations:

        # Put all query strings together and remove dupes
        queries = set([q
                       for l in [args.station, args.find,
                                 args.random, args.randomStations]
                       if l
                       for q in l])

        # Compile list of stations found
        stationMatches = []
        for query in queries:
            if re.match('^[0-9]+$', query):
                # Station ID
                stationMatches.append(Station(query))

            else:
                stations = Songza.findStations(query)

                if not stations:
                    log.error('No stations found for query: %s', query)

                stationMatches.extend(stations)

        # Search only names
        if args.namesOnly:
            stationMatches = [station
                              for q in queries
                              for station in stationMatches
                              if q.lower() in station.name.lower()]

        # Exclude stations
        if args.exclude:
            countBefore = len(stationMatches)
            stationMatches = [station
                              for e in args.exclude
                              for station in stationMatches
                              if e.lower() not in station.name.lower()]
            countAfter = len(stationMatches)

            log.debug('Excluded %s stations.  Stations remaining: %s',
                      countBefore - countAfter, [station.name for station in stationMatches])

        # Remove dupes
        stationMatches = set(stationMatches)

        # Sort
        stationMatches = sorted(stationMatches,
                                key=lambda station: getattr(station, sortBy),
                                reverse=sortReverse)

        if not stationMatches:
            log.error('No stations found.')
            return False

        if args.find:
            # Just print matches
            printStations(stationMatches)
            return True

        else:
            # Play stations

            if len(stationMatches) == 1:
                # One station found; play it
                player.station = stationMatches[0]
                player.play()

            else:
                # Multiple stations found

                if args.random:
                    # Play one random station
                    player.station = random.choice(stationMatches)
                    player.play()

                elif args.randomStations:
                    # Play random stations one track at a time
                    player.stations = stationMatches
                    player.random = True
                    player.play()

                else:
                    printStations(stationMatches)
                    return False


if __name__ == '__main__':
    sys.exit(main())
