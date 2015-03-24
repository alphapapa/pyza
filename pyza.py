#!/usr/bin/env python

# * pyza.py
# Based on MixZaTape

# ** Imports
import argparse
import logging
import random
import re
import requests
import subprocess
import sys
import time
import demjson

from bs4 import BeautifulSoup
from collections import namedtuple

# ** Classes
# *** Songza
class Songza(object):
    REQUEST_HEADERS = {"Content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                       "Accept": "application/json, text/javascript, */*; q=0.01",
                       "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X"
                       + "10_8_3) AppleWebKit/537.36 (KHTML, like Gecko)"
                       + "Chrome/27.0.1453.93 Safari/537.36"}
    SONGZA_URL_PREFIX = 'https://songza.com'

    ACTIVITY_PATH ="/discover/activities/"
    GENRE_PATH = "/discover/genres/"
    MOOD_PATH = "/discover/moods/"
    SEARCH_PATH = '/api/1/search/station'

    Category = namedtuple('category', 'singular plural path')

    CATEGORIES = {'activities': Category('activity', 'activities', ACTIVITY_PATH),
                  'genres': Category('genre', 'genres', GENRE_PATH),
                  'moods': Category('mood', 'moods', MOOD_PATH)}

    logger = logging.getLogger('pyza').getChild('Songza')

    @staticmethod
    def request(path, params=None, method='get'):
        '''Returns a requests result for a request.'''

        url = Songza.SONGZA_URL_PREFIX + path

        return getattr(requests, method)(url, params=params,
                                           headers=Songza.REQUEST_HEADERS)

    @staticmethod
    def findStations(query):
        '''Returns list of Stations for query string.'''

        category = None

        # Get activity/genre/mood from query
        for categoryType, c in Songza.CATEGORIES.iteritems():
            prefixes = [c.singular, c.singular[0]]  # Single-letter abbreviations

            for p in prefixes:
                if "%s:" % p in query:
                    category = c
                    
                    # Get the query part
                    q = re.sub('^.*:', '', query)

                    # Set the category in the query to the full
                    # category string for clarity in output
                    query = "%s:%s" % (c.singular, q)

                    break

        json = []

        # Category search
        if category:
            # Get the HTML for the category query
            response = Songza.request(category.path + q)

            # If it returns an error page, it's probably a
            # non-existent category
            if response.ok:
                # Decode the StationCache JSON object
                json = Songza._decodeStationCache(response.text)

        # Plain search
        else:
            json = Songza.request(Songza.SEARCH_PATH, params={'query': query}).json()

        stations = [Station(str(station['id']), station['name'],
                        station['song_count'], station['description'])
                    for station in json]

        Songza.logger.debug('Found %s stations for query "%s": %s',
                            len(stations), query, [station for station in stations])

        return stations


    @staticmethod
    def getCategory(category):
        '''Returns list of categories for a category type (activities, moods, or genres).'''

        category = Songza.CATEGORIES[category]
        response = Songza.request(category.path).text

        return Songza._decodeCategory(response, category)

    @staticmethod
    def _decodeCategory(html, category):
        '''Returns list of categories (activities, genres, moods) for a given
        Songza /discover/ page's HTML.'''

        soup = BeautifulSoup(html)
        raw = soup.findAll('script', text=re.compile('tag: "%s"' % category.plural))[0].text

        # Narrow down the raw <script... element
        start = re.search('App.getInstance\(\).trigger\("nav-keep-open-subnav", {', raw).end()
        raw = raw[start-1:]
        end = re.search('\n\s*}\);\s*\n', raw).start()

        # Just add the brace at the end. Easier than fiddling with the
        # end of the raw string.
        json = demjson.decode(raw[:end] + '}')

        categories = [c['slug'] for c in json['galleries']]

        return categories

    @staticmethod
    def _decodeStationCache(html):
        """
        Returns list of dicts of stations for Songza HTML.

        In the Songza pages there is a JSON with all of the staton
        info contained in Models.StationCache.set(.  We get all of the
        data contained in the curly braces and convert it to a JSON
        using demjson, becausePython's builtin JSON module is too
        strict for this JSON's strucure.  The keys of the JSON are the
        station IDs and the values are the dicts we'd get from the
        API.  So we only return the values of the decoded JSON.

        """

        # TODO: Should we use BeautifulSoup for this?
        start =  re.search('Models.StationCache.set\(', html).end()
        html = html[start:]
        end =  html.find('})') + 1

        return demjson.decode(html[:end]).values()


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
        return '%s: "%s" from "%s" (%s)' % (self.artist, self.title, self.album, self.genre)

    __str__ = __repr__


class Station(object):

    def __init__(self, stationID=None, name=None, songCount=None, description=None):
        self.log = logging.getLogger(self.__class__.__name__)

        assert(stationID or name)

        self.id = stationID
        self.name = name.encode('utf8') if name else None
        self.songCount = songCount
        self.description = description.encode('utf8') if description else None

        self.previousTrack = None
        self.track = None
        self.nextTrack = None
        self.trackStartTime = None

        self.path = "/api/1/station/" + self.id

        # Get station name/songcount if not set
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

        self.log.debug('New track for station %s (%s): %s',
                       self.name, self.id, self.track)

        return self.track

    def _vote(self, direction):
        result = Songza.request("/api/1/station/%s/song/%s/vote/%s" %
                                (self.id, self.track.id, direction),
                                method='post')

        self.log.debug(result)

    def downVote(self):
        self._vote('down')

    def upVote(self):
        self._vote('up')

# *** Player
class Player(object):
    def __init__(self, excludes=None, logger=None):
        self.log = logger.getChild(self.__class__.__name__)

        self.excludes = excludes

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

        self.nextTrack = None
        while not self.nextTrack:
            if self.random:
                self.station = random.choice(self.stations)
                self.log.info('Next station: %s', self.station)

            self.nextTrack = self.station.next()

            # Check track against excludes.  Do not check genre,
            # because Songza does things like use the genre
            # "Classical/Opera" for all classical tracks, even if they
            # have nothing to do with opera.
            if self.excludes:
                if any(e in t
                       for t in [self.nextTrack.artist.lower(), self.nextTrack.album.lower(),
                                 self.nextTrack.title.lower()]
                       for e in self.excludes):

                    self.log.info('Excluding track: %s', self.nextTrack)

                    self.nextTrack = None

        self.log.debug('Next track: %s', self.nextTrack)

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

        self.log.info("Playing track: %s", self.track)

    def play(self):
        '''Starts playing the station or stations.'''

        # Get and play the next track
        self.next()

        self.paused = False
        self.playing = True
        self.stopped = False


class MPD(Player):
    DEFAULT_PORT = 6600

    def __init__(self, host, port=DEFAULT_PORT, password=None, **kwargs):
        self.host = host
        self.port = port
        self.password = password

        # Import python-mpd2.  This might not be the "correct" way to
        # do this, putting the import down here, but this way people
        # can use the script without having python-mpd2.
        import mpd
        if mpd.VERSION < (0, 5, 4):
            self.log.critical('Using MPD requires python-mpd >= 0.5.4 (aka python-mpd2).')
            raise Exception

        super(MPD, self).__init__(**kwargs)

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
            self.log.debug("Connection lost to server: %s.  Reconnecting...",
                           self.host)

            try:
                self.mpd.connect(self.host, self.port)
            except:
                self.log.critical("Couldn't reconnect to server: %s",
                                  self.host)
                raise Exception
            else:
                self.log.debug("Reconnected to server: %s", self.host)

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
        self._addTags(songID, track)

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

    def  _addTags(self, songID, track):
        '''Adds artist/album/title/genre tags to a songID.'''

        self._checkConnection()

        # Start command list
        self.mpd.command_list_ok_begin()

        self.mpd.addtagid(songID, 'artist', track.artist)
        self.mpd.addtagid(songID, 'album', track.album)
        self.mpd.addtagid(songID, 'title', track.title)

        # Clear the genre tag first, because tracks can have multiple
        # genres in MPD, and if you add the same genre tag twice, it
        # will show up twice
        self.mpd.cleartagid(songID, 'genre')
        self.mpd.addtagid(songID, 'genre', track.genre)

        # Execute command list
        self.mpd.command_list_end()

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

        self.currentSong = self.mpd.currentsong()

    def play(self):
        '''Calls parent play() method to set the current station, then
        monitors MPD and adds the next track when necessary.'''

        super(MPD, self).play()
        lastSongID = self.songID

        # Loop waiting for track change
        while True:

            # Wait for a change
            self.mpd.idle()

            # Get player status info
            self._status()

            # Add the next song when the current song changes
            if lastSongID != self.songID:
                self.log.debug('Song changed.  Last song:%s  Current song:%s',
                               lastSongID, self.songID)

                self.next()
                lastSongID = self.songID

                # Set the tags again, since they seem to get messed up
                if ('artist' not in self.currentSong
                    or self.currentSong['artist'] != self.track.artist):

                    self.log.debug('Tags disappeared.  Adding again...')

                    self._addTags(self.songID, self.track)


class VLC(Player):
    def __init__(self, **kwargs):
        super(VLC, self).__init__(**kwargs)

        self.player = VlcPlayer()

        self.log.debug("Initialized VLC Player.")

    def _next(self):
        '''Gets next track and plays it.'''

        self._getNextTrack()
        self.track = self.nextTrack
        self.player.play(self.track.url)

    def _status(self):
        '''Updates player status and position.'''

        # In this future this may be used to let VLC skip tracks.
        # Right now it's unused.

        self.position = self.player.getTime()

    def play(self):
        '''Calls parent play() method, then loops, sleeping for the track's
        duration and then starting the next track.'''

        super(VLC, self).play()

        # Loop
        while True:

            if not self.track.duration:
                self.log.critical('Duration not available for track: %s.  This should not happen.',
                                  self.track)
                raise Exception

            sleepTime = self.track.duration

            self.log.debug('Sleeping for %s seconds', sleepTime)

            # Wait for the track to finish playing
            time.sleep(float(sleepTime))

            self.next()


class VlcPlayer:

    REGEXP_TIME_REMAINING = re.compile('[> ]*(\d*)\r\n')

    def __init__(self):
        self.log = logging.getLogger().getChild(self.__class__.__name__)

        self.process = None
        self.paused = None
        self.time = None

    def _sendCommand(self, command, readline=False):
        '''Sends the specified command to the player.  If readline is True,
        returns a line of response from STDOUT.'''

        self.process.stdin.write(command + "\n".encode("utf-8"))

        if readline:
            return self.process.stdout.readline()

    def volumeUp(self):
        self._sendCommand("volup")

    def volumeDown(self):
        self._sendCommand("voldown")

    def pause(self):
        self.paused = True
        self._sendCommand("pause")

    def stop(self):
        self._sendCommand("shutdown")
        self.process = None
        self.paused = None

    def enqueue(self, file):
        self._sendCommand("enqueue " + file)

    def skip(self):
        self._sendCommand("next")
        self.time = 0

    def seek(self, seconds):
        self._sendCommand("seek {0}".format(seconds))

    def getTime(self):
        '''Gets time elapsed, sets self.time, and returns it.'''

        try:
            self.time = int(self._sendCommand("get_time", readline=True)[2:])
        finally:
            # Sometimes when seeking, VLC is slow to respond, and the
            # STDOUT output gets out of sync. In this case, return the
            # last known time value.
            return self.time

    def play(self, file):
        '''Plays file, either enqueueing in existing process or starting VLC.'''

        if self.process:
            # Already running
            self.enqueue(file)
            self.skip()
        else:
            # Not running; start VLC
            self.process = subprocess.Popen(["vlc", "-Irc", "--quiet", file],
                                            shell=False,
                                            stdout=subprocess.PIPE,
                                            stdin=subprocess.PIPE,
                                            stderr=subprocess.STDOUT)
            self.process.stdout.readline()
            self.process.stdout.readline()

        self.paused = False

    def getTimeRemaining(self):
        '''Returns time remaining in seconds.'''

        duration = None
        remaining = None
        timeRemaining = None

        try:
            response = self._sendCommand("get_length", readline=True)
            match = VlcPlayer.TIME_REMAINING_REGEX.search(response)

            if match:
                duration = int(match.group(1))
            else:
                self.log.debug("Unable to parse duration: %s",
                                  response)

            response = self._sendCommand("getTime", readline=True)
            match = VlcPlayer.TIME_REMAINING_REGEX.search(response)

            if match:
                remaining = int(match.group(1))
            else:
                self.log.debug("Unable to parse time remaining: %s",
                                  response)

            if duration and remaining:
                timeRemaining = duration - remaining

        except Exception:
            self.log.exception("Couldn't get time remaining:")

        return timeRemaining

# ** Functions
def printStations(stations, query):
    print '%s stations found for query "%s":' % (len(stations),
                                                 ' '.join([q for q in query]))
    for station in sorted(stations, key=lambda s: s.name):
        print station


def main():

    # **** Parse args
    parser = argparse.ArgumentParser(description='A terminal-based Songza client.  Plays with VLC by default.  Queries may be plain queries which will match against station names and descriptions, or they may be in the form of {activity|a,genre|g,mood|m}:query to search for stations by activity, genre, or mood.  For example: "pyza -f reading" or "pyza -f genre:jazz" or "pyza -f mood:happy" ')
    parser.add_argument('-l', '--list-categories',
                        dest='listCategories', nargs='*',
                        choices=Songza.CATEGORIES.keys(),
                        help="Display list of available categories")
    parser.add_argument('-e', '--exclude', nargs='*',metavar='QUERY',
                        help="Exclude stations matching queries")
    parser.add_argument('-f', '--find', nargs='*',metavar='QUERY',
                        help="List stations matching queries")
    parser.add_argument('-n', '--names-only', action='store_true',
                        dest='namesOnly',
                        help="Only search station names, not station descriptions or other data")
    parser.add_argument('-m', '--mpd', nargs='?', metavar='HOST[:PORT]',
                        const='localhost:6600',
                        help="Play with MPD server.  Default: localhost:6600")
    parser.add_argument('-r', '--random', nargs='*',metavar='QUERY',
                        help="Play one random station matching query")
    parser.add_argument('-R', '--random-stations', nargs='*',metavar='QUERY',
                        dest='randomStations',
                        help="Play one song each from random stations matching queries")
    parser.add_argument('-s', '--station', nargs='*', metavar='STATION',
                        help="A station name, partial station name, or station ID number")
    parser.add_argument('--sort', dest='sort', choices=['name', 'songs', 'id'],
                        default='songs',
                        help="Sort station list.  Default: number of songs")
    parser.add_argument("-v", "--verbose", action="count", dest="verbose", help="Be verbose, up to -vv")
    args = parser.parse_args()

    # **** Setup logging
    if args.verbose == 1:
        LOG_LEVEL = logging.INFO

        # Stop requests' INFO messages, which really should be DEBUGs
        logging.getLogger("requests").setLevel(logging.WARNING)

    elif args.verbose >= 2:
        LOG_LEVEL = logging.DEBUG
    else:
        LOG_LEVEL = logging.WARNING

    logging.basicConfig(level=LOG_LEVEL, format="%(levelname)s: %(name)s: %(message)s")

    log = logging.getLogger('pyza')

    log.debug("Args: %s", args)

    # **** Check args
    if not (args.find or args.station or args.random or args.randomStations) and args.listCategories is None:
        log.error('Please provide a station or search string.')
        parser.print_help()
        return False

    if args.find and args.station:
        log.error('Please use either -f or -s but not both.')
        return False

    if args.random and args.randomStations:
        log.error('Please use either -r or -R but not both.')
        return False

    # **** List categories
    if args.listCategories is not None:

        # TODO: Calculate number of columns that can fit in available
        # term width

        # If none given, use all
        if not args.listCategories or args.listCategories == ['all']:
            args.listCategories = Songza.CATEGORIES

        categories = {category: Songza.getCategory(category) for category in args.listCategories}

        if categories:
            for k, v in categories.iteritems():
                colHeight = len(v) / 3
                print "%s %s:" % (len(v), k)

                # Print in columns: http://stackoverflow.com/a/1524225
                print "\n".join("%-40s %-40s %s" %
                                (v[i],
                                 v[i + colHeight],
                                 v[i + colHeight * 2])
                                for i in range(colHeight))
                print  # blank line

            return True

        else:
            log.error("No categories found?  Oops...")

            return False

    # **** Handle sort arg
    sortReverse = False
    if args.sort:
        if args.sort == 'songs':
            sortBy = 'songCount'
        elif args.sort == 'id':
            sortBy = 'id'
            sortReverse = True
        else:
            sortBy = 'name'

    # **** Play or list stations
    if args.station or args.find or args.random or args.randomStations:

        # ***** Put together station list
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
                # Station ID number
                stationMatches.append(Station(query))

            else:
                # Search for string
                stations = Songza.findStations(query)

                if not stations:
                    log.error('No stations found for query: %s', query)
                    continue

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
                              for station in stationMatches
                              if not any(e.lower() in s
                                         for s in [station.name.lower(), station.description.lower()]
                                         for e in args.exclude)]
            countAfter = len(stationMatches)

            log.debug('Excluded %s stations.  Stations remaining: %s',
                      countBefore - countAfter, [station.name for station in stationMatches])

        # Remove dupes
        stationMatches = set(stationMatches)

        # Sort
        stationMatches = sorted(stationMatches,
                                key=lambda station: getattr(station, sortBy),
                                reverse=sortReverse)

        # Check result
        if not stationMatches:
            log.error('No stations found.')
            return False

        # ***** List or play stations
        if args.find:
            # ****** List stations
            printStations(stationMatches, queries)
            return True

        else:
            # ****** Play stations

            # ******* Setup player
            if args.mpd:
                # ******** Play with MPD

                # Get host and port
                if len(args.mpd) > 0:
                    # Host given
                    if ':' in args.mpd:
                        # Port given
                        host, port = args.mpd.split(':')
                    else:
                        # Use given host and default port
                        host = args.mpd
                        port = MPD.DEFAULT_PORT
                else:
                    # Use default host and port
                    host = 'localhost'
                    port = MPD.DEFAULT_PORT

                try:
                    player = MPD(host, port, excludes=args.exclude, logger=log)
                except Exception as e:
                    log.critical("Couldn't connect to MPD server: %s:%s: %s", host, port, e)
                    return False
                else:
                    log.debug('Connected to MPD server: %s', host)

            else:
                # ******** Play with VLC
                try:
                    player = VLC(excludes=args.exclude, logger=log)
                except Exception as e:
                    log.critical("Couldn't launch VLC: %s", e)
                    return False


            # ******* Play stations
            if len(stationMatches) == 1:
                # ******** One station found; play it
                player.station = stationMatches[0]
                player.play()

            else:
                # ******** Multiple stations found

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
                    # Just list stations
                    printStations(stationMatches, queries)
                    return False

# ** __main__
if __name__ == '__main__':
    sys.exit(main())
