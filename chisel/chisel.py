import argparse
import asyncio
import json
import logging
from datetime import datetime
from random import normalvariate
from time import time_ns

import aiohttp


async def run_request_tensorflight(data, client):
    logger = logging.getLogger(f'worker_{data["id"]:05}')
    logger.setLevel(logging.INFO)

    if 'sleep' in data:
        await asyncio.sleep(data['sleep'])

    logger.info('Requesting processing...')

    data['request_processing'] = dict()

    drp = data['request_processing']
    drp['start'] = time_ns()

    async with client.post(
        f'{data["domain"]}/api/request_processing_location',
        json=data['json'],
    ) as resp:
        try:
            status = resp.status
            if status not in (200, 400, 403):
                logger.error(f'Unexpected status code from request_processing_location! {status}')
            drp['status'] = status
            drp['json'] = await resp.json()
        except Exception as e:
            logger.debug(e)
            logger.warning('Request failed, aborting...')
            drp['end'] = time_ns()
            return False

    try:
        if drp['json']['status'] != 'SUCCESS':
            logger.info('Did not receive success!')
            raise Exception
        plan_id = drp['json']['plan_id']
    except Exception as e:
        print(e)
        logger.warning('Request failed, aborting...')
        drp['end'] = time_ns()
        return False

    drp['end'] = time_ns()

    logger.debug(plan_id)

    logger.info('Moving onto getting features')

    # from the back, total wait is cumulative
    base_wait = normalvariate(mu=35, sigma=5)
    waits = [base_wait * (0.75 ** i) for i in range(12)]
    cumwaits = [sum(waits[i:]) for i in range(len(waits))]

    data['get_features'] = []
    while len(waits):
        await asyncio.sleep(waits[-1])
        logger.info(f'Slept for {waits[-1]} ({cumwaits[-1]} total)')
        dgf = {
            'wait': waits[-1],
            'cumwait': cumwaits[-1],
            'start': time_ns(),
        }
        data['get_features'].append(dgf)
        waits.pop()
        cumwaits.pop()
        async with client.post(
            f'{data["domain"]}/api/get_features',
            json={
                'plan_id': plan_id,
                'api_key': data['json']['api_key'],
            },
        ) as resp:
            try:
                dgf['status'] = resp.status
                dgf['json'] = await resp.json()
            except Exception:
                logger.info('Request failed')

        dgf['end'] = time_ns()

        logger.debug(dgf)
        try:
            if dgf['status'] == 200:
                logger.info('Got results!')
                break
            if dgf['status'] not in (200, 202, 400, 403):
                logger.error(f'Unexpected status code from get_features! {dgf["status"]}')
        except Exception:
            pass
    else:
        return False

    return True


async def async_main():
    parser = argparse.ArgumentParser(
        description='''aiohttp based throughput and stress tester''',
        epilog='''
Barebones usage:
    python chisel.py  DOMAIN API_KEY ADDRESSES_FILE
100 requests in (about) 1s, at random from file
    python chisel.py --limit 100 --stagger 0.01 --shuffle  DOMAIN API_KEY ADDRESSES_FILE
Make delays normally distributed (mean 0.015, stddev 0.04):
    python chisel.py --limit 100  --stagger 0.015 --deviation 0.04 --shuffle  DOMAIN API_KEY ADDRESSES_FILE 
''',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument('domain', type=str)
    parser.add_argument('api_key', type=str)
    parser.add_argument('data', type=str, help='File with addresses for requests')

    parser.add_argument('-s', '--shuffle', action='store_true')
    parser.add_argument('-l', '--limit', type=int, required=False, default=0)
    parser.add_argument('-S', '--stagger', '--sleep', type=float, required=False, default=0,
                        help='Time to sleep between requests (passed to time.sleep())')
    parser.add_argument('-d', '--deviation', type=float, required=False,
                        help='When provided, stagger will be normally distributed with this stddev')

    args = parser.parse_args()
    logging.basicConfig(format='[%(levelname)s] %(name)s %(asctime)s.%(msecs)03d:\t%(message)s',
                        datefmt='%m/%d/%Y %H:%M:%S')

    report_file = f'chisel-report-{datetime.now().isoformat()}.json'
    try:
        with open(report_file, 'w'):
            pass
    except Exception:
        while True:
            confirm = input(f'Unable to create report file {report_file}, continue? [y/n]')
            if confirm in 'nN':
                print('Aborting.')
                exit(124)
            if confirm in 'yY':
                break

    with open(args.data, 'r') as f:
        data = [l.strip('\n"') for l in f]

    url_cnt = len(data)

    if args.shuffle:
        order = list(range(url_cnt))
        from random import shuffle
        shuffle(order)
        data = [data[i] for i in order]

    print(f'Got {url_cnt} urls')

    if args.limit != 0:
        limit = min(url_cnt, args.limit)
        data = data[:limit]

    url_cnt = len(data)
    print(f'Keeping {url_cnt} urls')

    schedule = [0]
    for _ in range(1, url_cnt):
        next_start = schedule[-1]

        if args.stagger or args.deviation:
            if args.deviation:
                next_start += max(0., normalvariate(mu=args.stagger, sigma=args.deviation))
            else:
                next_start += max(0., args.stagger)

        schedule.append(next_start)

    while True:
        print(f'About to schedule {len(schedule)} tasks.')
        print(f'The first starts at {schedule[0]}, the last at {schedule[-1]}.')
        if len(schedule) > 10 and schedule[-1] > 1e-6:
            print(f'This leads to a combined rate of {len(schedule) / schedule[-1]} requests per second.')
        confirm = input('Does this look ok? [y/n] ')
        if confirm in 'nN':
            print('Aborting.')
            exit(123)
        if confirm in "yY":
            break

    if ('tensorflight' in args.domain) or True:  # tmp default handler
        print('Using tensorflight handler')
        data = [{
            'id': i,
            'domain': args.domain,
            'sleep': sleep,
            'json': {
                'address': address,
                'api_key': args.api_key,
            }
        } for i, (address, sleep) in enumerate(zip(data, schedule))]

        print(f'Starting at {datetime.now().isoformat()}')

        tasks = []
        async with aiohttp.ClientSession() as client:
            for i in range(len(data)):
                task = asyncio.create_task(
                    run_request_tensorflight(
                        data[i],
                        client,
                    )
                )
                tasks.append(task)

            result = await asyncio.gather(*tasks)

        print(f'Done at {datetime.now().isoformat()}')
        print(f'{sum(1 if res else 0 for res in result)}/{len(result)} OK')

        with open(report_file, 'w') as f:
            json.dump(data, fp=f, default=str)
        print(f'Saved data to {report_file}')
        return result


def main():
    asyncio.run(async_main())


if __name__ == '__main__':
    main()
