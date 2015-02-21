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
    REQUEST_HEADERS = {
        "Content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_8_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/27.0.1453.93 Safari/537.36"}

    @staticmethod
    def request(path, params=None, method='get'):
        '''Returns a requests result for a request.'''

        url = Songza.SONGZA_URL_PREFIX + path

        return getattr(requests, method)(url, params=params, headers=Songza.REQUEST_HEADERS)

    @staticmethod
    def findStations(query):
        '''Returns list of Station objects for query string.'''

        r = Songza().request("/api/1/search/station", params={'query': query})

        stations = [Station(str(station['id']), station['name'], station['song_count']) for station in r.json()]

        log.debug('Found stations for query: %s' % ([str(station) for station in stations]))

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
        return "%s - %s, %s (%s): %s: %s" % (self.artist, self.album, self.title, self.genre, self.id, self.url)

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
    def __init__(self, stationID, name=None, songCount=None):
        self.id = stationID
        self.name = name.encode('utf8')
        self.songCount = songCount

        self.previousTrack = None
        self.track = None
        self.nextTrack = None
        self.trackStartTime = None

        self.stationPath = "/api/1/station/" + self.id

        # TODO: Get station name/songcount if not set

    def __repr__(self):
        return self._reprstr()

    def __str__(self):
        return self._reprstr()

    def _reprstr(self):
        return '%s: %s (%s songs)' % (self.id, self.name, self.songCount)

    def next(self):
        '''Set the station's current track to the next track.'''

        params = {"cover_size": "m", "format": "aac", "buffer": 0}
        result = Songza.request(self.stationPath + '/next', params=params, method='post').json()

        self.previousTrack = self.track if self.track else None
        self.track = Track(result['listen_url'], result['song'])

        log.debug('New track for station %s: %s: %s' % (self.id, self.track.artist, self.track.title))

        return self.track

    def _vote(self, direction):
        result = Songza.request("/api/1/station/%s/song/%s/vote/%s" % (self.id, self.track.id, direction), method='post')

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

        self.random = False
        self.stations = None

        self.vlc = VlcPlayer()

    def play(self):
        '''Plays the station or stations in VLC.'''

        if self.random:
            self.station = random.choice(self.stations)
            log.debug('Playing station: %s' % self.station)

        if self.paused:
            self.vlc.play()
            self.paused = False
            self.playing = True

        elif self.stopped:
            # Get and play the next track
            self.track = self.station.next()
            self.vlc.play(self.track.url)

            self.paused = False
            self.playing = True
            self.stopped = False

        # Loop
        while True:

            # Get the sleep time from VLC, but it doesn't have the
            # time remaining until it has downloaded some of the file
            sleepTime = None
            tries = 0
            while not sleepTime and tries < 10:  # 2 seconds
                time.sleep(0.2)
                sleepTime = self.vlc.time_remaining()
                tries += 1
            if not sleepTime:
                log.error('No time remaining reported by VLC.  Maybe the track failed to download.')
                raise

            log.debug('Sleeping for %s seconds' % sleepTime)

            # Wait for the track to finish playing
            time.sleep(float(sleepTime))

            if self.random:
                # Choose another random station
                self.station = random.choice(self.stations)
                log.debug('Now playing station: %s' % self.station)

                self.track = self.station.next()
                self.vlc.play(self.track.url)
            else:
                # Get and play the next track
                self.track = self.station.next()
                self.vlc.play(self.track.url)

def main():

    # Parse args
    parser = argparse.ArgumentParser(description='A terminal-based Songza client.')
    parser.add_argument('-e', '--exclude', nargs='*',
                        help="Exclude stations matching strings")
    parser.add_argument('-f', '--find', nargs='*',
                        help="List stations matching query strings")
    parser.add_argument('-n', '--names-only', action='store_true',
                        dest='namesOnly',
                        help="Only search station names, not station descriptions or other data")
    parser.add_argument('-r', '--random', action='store_true',
                        help="Play one random station matching query string")
    parser.add_argument('-R', '--random-stations', action='store_true',
                        dest='randomStations',
                        help="Play one song each from random stations matching query strings")
    parser.add_argument('-s', '--station', nargs='*',
                        help="A station name, partial station name, or station ID number")
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

    log.debug("Args: %s" % args)

    # Check args
    if not (args.find or args.station):
        log.error('Please provide a station or search string.')
        parser.help()
        return False

    if args.find and args.station:
        log.error('Please use -f or -s but not both.')
        return False

    if args.random and args.randomStations:
        log.error('Please use either -r or -R but not both.')
        return False

    # Player object
    player = Player()

    # Handle args
    if args.station or args.find:

        queries = args.station or args.find

        # Compile list of stations found
        stationMatches = []
        for station in queries:
            if re.match('^[0-9]+$', station):
                # Station ID
                stationMatches.append(Station(station))

            else:
                stations = Songza.findStations(station)

                if not stations:
                    log.error('No stations found for query: %s' % station)

                stationMatches.extend(stations)

        # Search only names
        if args.namesOnly:
            stationMatches = [station for q in queries for station in stationMatches if q.lower() in station.name.lower()]

        # Exclude stations
        if args.exclude:
            countBefore = len(stationMatches)
            stationMatches = [station for e in args.exclude for station in stationMatches if e.lower() not in station.name.lower()]
            countAfter = len(stationMatches)

            log.debug('Excluded %s stations.  Stations remaining: %s' % (countBefore - countAfter, [station.name for station in stationMatches]))

        if not stationMatches:
            log.error('No stations found.')
            return False

        if len(stationMatches) == 1:
            # One station found; play it
            player.station = stationMatches[0]
            player.play()

        else:
            # Multiple stations found

            if args.random:
                # Play one random station
                player.station = random.choice(stationMatches)
                print player.station
                player.play()

            elif args.randomStations:
                # Play random stations one track at a time
                player.stations = stationMatches
                player.random = True
                player.play()

            else:
                # Print list of stations
                print '%s stations found:' % len(stationMatches)
                for station in stationMatches:
                    print station
                return False


if __name__ == '__main__':
    sys.exit(main())
