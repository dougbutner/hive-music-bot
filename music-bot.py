#!/usr/bin/env python3
'''A script to findm and react to PIZZA commands in comments'''
from beem import Hive
from beem.account import Account
from beem.blockchain import Blockchain
from beem.comment import Comment
from beem.discussions import Query, Discussions_by_feed
import beem.instance
import os
import jinja2
import configparser
import time
import json
import requests
import sqlite3
from datetime import date


from hiveengine.wallet import Wallet

### Global configuration

BLOCK_STATE_FILE_NAME = 'lastblock.txt'

config = configparser.ConfigParser()
config.read('pizzabot.config')

ENABLE_COMMENTS = config['Global']['ENABLE_COMMENTS'] == 'True'
ENABLE_TRANSFERS = config['HiveEngine']['ENABLE_TRANSFERS'] == 'True'
ENABLE_DISCORD = config['Global']['ENABLE_DISCORD'] == 'True'

ACCOUNT_NAME = config['Global']['ACCOUNT_NAME']
ACCOUNT_POSTING_KEY = config['Global']['ACCOUNT_POSTING_KEY']
HIVE_API_NODE = config['Global']['HIVE_API_NODE']
HIVE = Hive(node=[HIVE_API_NODE], keys=[config['Global']['ACCOUNT_ACTIVE_KEY']])
HIVE.chain_params['chain_id'] = 'beeab0de00000000000000000000000000000000000000000000000000000000'
beem.instance.set_shared_blockchain_instance(HIVE)
ACCOUNT = Account(ACCOUNT_NAME)
TOKEN_NAME = config['HiveEngine']['TOKEN_NAME']

BOT_COMMAND_STR = config['Global']['BOT_COMMAND_STR']
ESP_BOT_COMMAND_STR = config['Global']['ESP_BOT_COMMAND_STR']
WEBHOOK_URL = config['Global']['DISCORD_WEBHOOK_URL']

SQLITE_DATABASE_FILE = 'pizzabot.db'
SQLITE_GIFTS_TABLE = 'pizza_bot_gifts'

### END Global configuration


print('Loaded configs:')
for section in config.keys():
    for key in config[section].keys():
        if '_key' in key: continue # don't log posting/active keys
        print('%s : %s = %s' % (section, key, config[section][key]))


# Markdown templates for comments
comment_fail_template = jinja2.Template(open(os.path.join('templates','comment_fail.template'),'r').read())
comment_outofstock_template = jinja2.Template(open(os.path.join('templates','comment_outofstock.template'),'r').read())
comment_success_template = jinja2.Template(open(os.path.join('templates','comment_success.template'),'r').read())
comment_daily_limit_template = jinja2.Template(open(os.path.join('templates','comment_daily_limit.template'),'r').read())
comment_curation_template = jinja2.Template(open(os.path.join('templates','comment_curation.template'),'r').read())

# Spanish language templates
esp_comment_fail_template = jinja2.Template(open(os.path.join('templates','esp_comment_fail.template'),'r').read())
esp_comment_outofstock_template = jinja2.Template(open(os.path.join('templates','esp_comment_outofstock.template'),'r').read())
esp_comment_success_template = jinja2.Template(open(os.path.join('templates','esp_comment_success.template'),'r').read())
esp_comment_daily_limit_template = jinja2.Template(open(os.path.join('templates','esp_comment_daily_limit.template'),'r').read())

### sqlite3 database helpers

def db_create_tables():
    db_conn = sqlite3.connect(SQLITE_DATABASE_FILE)
    c = db_conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS %s(date TEXT NOT NULL, invoker TEXT NOT NULL, recipient TEXT NOT NULL, block_num INTEGER NOT NULL);" % SQLITE_GIFTS_TABLE)

    db_conn.commit()
    db_conn.close()


def db_save_gift(date, invoker, recipient, block_num):

    db_conn = sqlite3.connect(SQLITE_DATABASE_FILE)
    c = db_conn.cursor()

    c.execute('INSERT INTO %s VALUES (?,?,?,?);' % SQLITE_GIFTS_TABLE, [
        date,
        invoker,
        recipient,
        block_num
        ])
    db_conn.commit()
    db_conn.close()


def db_count_gifts(date, invoker):

    db_conn = sqlite3.connect(SQLITE_DATABASE_FILE)
    c = db_conn.cursor()

    c.execute("SELECT count(*) FROM %s WHERE date = '%s' AND invoker = '%s';" % (SQLITE_GIFTS_TABLE,date,invoker))
    row = c.fetchone()

    db_conn.commit()
    db_conn.close()

    return row[0]


def db_count_gifts_unique(date, invoker, recipient):

    db_conn = sqlite3.connect(SQLITE_DATABASE_FILE)
    c = db_conn.cursor()

    c.execute("SELECT count(*) FROM %s WHERE date = '%s' AND invoker = '%s' AND recipient = '%s';" % (SQLITE_GIFTS_TABLE,date,invoker,recipient))
    row = c.fetchone()

    db_conn.commit()
    db_conn.close()

    return row[0]


def get_account_posts(account):
    acc = Account(account)
    account_history = acc.get_account_history(-1, 5000)
    account_history = [x for x in account_history if x['type'] == 'comment' and not x['parent_author']]

    return account_history


def get_account_details(account):
    acc = Account(account)
    return acc.json()


def get_block_number():

    if not os.path.exists(BLOCK_STATE_FILE_NAME):
        return None

    with open(BLOCK_STATE_FILE_NAME, 'r') as infile:
        block_num = infile.read()
        block_num = int(block_num)
        return block_num


def set_block_number(block_num):

    with open(BLOCK_STATE_FILE_NAME, 'w') as outfile:
        outfile.write('%d' % block_num)


def has_already_replied(post):

    for reply in post.get_replies():
        if reply.author == ACCOUNT_NAME:
            return True

    return False


def post_comment(parent_post, author, comment_body):
    if ENABLE_COMMENTS:
        print('Commenting!')
        parent_post.reply(body=comment_body, author=author)
        # sleep 3s before continuing
        time.sleep(3)
    else:
        print('Debug mode comment:')
        print(comment_body)

def post_discord_message(username, message_body):
    if not ENABLE_DISCORD:
        return

    payload = {
        "username": username,
        "content": message_body
    }

    try:
        requests.post(WEBHOOK_URL, data=payload)
    except:
        print('Error while sending discord message. Check configs.')



def daily_limit_reached(invoker_name, level=1):

    today = str(date.today())
    today_gift_count = db_count_gifts(today, invoker_name)

    access_level = 'AccessLevel%d' % level

    if today_gift_count >= int(config[access_level]['MAX_DAILY_GIFTS']):
        return True

    return False


def daily_limit_unique_reached(invoker_name, recipient_name, level=1):

    today = str(date.today())
    today_gift_count_unique = db_count_gifts_unique(today, invoker_name, recipient_name)

    access_level = 'AccessLevel%d' % level

    if today_gift_count_unique >= int(config[access_level]['MAX_DAILY_GIFTS_UNIQUE']):
        return True

    return False


def get_invoker_level(invoker_name):

    # check how much TOKEN the invoker has
    wallet_token_info = Wallet(invoker_name).get_token(TOKEN_NAME)

    if not wallet_token_info:
        invoker_balance = 0
        invoker_stake = 0
    else:
        invoker_balance = float(wallet_token_info['balance'])
        invoker_stake = float(wallet_token_info['stake'])


    # does invoker meet level 2 requirements?
    min_balance = float(config['AccessLevel2']['MIN_TOKEN_BALANCE'])
    min_staked = float(config['AccessLevel2']['MIN_TOKEN_STAKED'])

    if invoker_balance + invoker_stake >= min_balance and invoker_stake >= min_staked:
        return 2

    # does invoker meet level 1 requirements?
    min_balance = float(config['AccessLevel1']['MIN_TOKEN_BALANCE'])
    min_staked = float(config['AccessLevel1']['MIN_TOKEN_STAKED'])

    if invoker_balance + invoker_stake >= min_balance and invoker_stake >= min_staked:
        return 1

    return 0


def is_block_listed(name):

    return name in config['HiveEngine']['GIFT_BLOCK_LIST'].split(',')


def can_gift(invoker_name, recipient_name):

    if invoker_name in config['HiveEngine']['GIFT_ALLOW_LIST']:
        return True

    if is_block_listed(invoker_name):
        return False

    if is_block_listed(recipient_name):
        return False

    level = get_invoker_level(invoker_name)

    if level == 0:
        return False

    if daily_limit_reached(invoker_name, level):
        return False

    if daily_limit_unique_reached(invoker_name, recipient_name, level):
        return False

    return True

def hive_posts_stream():
    db_create_tables()
    hive = Hive(node=[HIVE_API_NODE])
    query = Query(limit=10, tag="music")

    while True:
        try:
            posts = Discussions_by_feed(query)
            for post in posts:
                author_account = post['author']
                permlink = post['permlink']
                reply_identifier = '@%s/%s' % (author_account, permlink)

                try:
                    post_comment_obj = Comment(reply_identifier)
                except beem.exceptions.ContentDoesNotExistsException:
                    print('post not found!')
                    continue

                # if we already commented on this post, skip
                if has_already_replied(post_comment_obj):
                    print("We already replied!")
                    continue

                # Create a comment
                comment_body = comment_success_template.render(
                    token_name=TOKEN_NAME,
                    target_account=author_account,
                    token_amount=0,  # No transfer in this example
                    author_account=author_account,
                    today_gift_count=0,  # Default values for the example
                    max_daily_gifts=0
                )

                post_comment(post_comment_obj, ACCOUNT_NAME, comment_body)
                
            time.sleep(60)  # Wait a minute before fetching new posts
        except Exception as e:
            print(f"An error occurred: {e}")
            time.sleep(60)  # Wait a minute before retrying

if __name__ == '__main__':
    hive_posts_stream()
