# -*- coding: utf-8 -*-
import json
from typing import Dict

import jmespath
from nested_lookup import nested_lookup
from scrapfly import ScrapflyClient, ScrapeConfig

import asyncio
import nest_asyncio
import pytz
import datetime
import requests
import os
import re
from urllib.parse import urlparse, parse_qs

key = "scp-live-72b62993c25742bb99bc92c83c52928c" # Your Scrapfly API Key
SCRAPFLY = ScrapflyClient(key= key)

# 設定台北時區
taipei_tz = pytz.timezone('Asia/Taipei')

image_save_path = f"./image/{datetime.datetime.now(taipei_tz).strftime('%m%d_%H%M')}"
os.makedirs(image_save_path, exist_ok=True)

taipei_tz = pytz.timezone('Asia/Taipei')
nest_asyncio.apply()

def download_image(image_url: str, save_folder: str) -> str:
    """Download images to our path and return the image name"""
    try:
        # 生成文件名稱
        parsed_url = urlparse(image_url)
        file_name = os.path.basename(parsed_url.path)
        file_name = re.sub(r'[<>:"/\\|?*]', '_', file_name)
        file_path = os.path.join(save_folder, file_name)

        response = requests.get(image_url, stream=True)
        response.raise_for_status()

        with open(file_path, "wb") as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
        return file_name  # 返回保存的路徑
    except Exception as e:
        print(f"下載失敗: {image_url}, 錯誤: {e}")
        return image_url

def parse_thread(data: Dict) -> Dict:
    """Parse Twitter tweet JSON dataset for the most important fields"""
    result = jmespath.search(
         """{
        text: post.caption.text,
        published_on: post.taken_at,
        id: post.id,
        pk: post.pk,
        code: post.code,
        username: post.user.username,
        user_pic: post.user.profile_pic_url,
        user_verified: post.user.is_verified,
        user_pk: post.user.pk,
        user_id: post.user.id,
        has_audio: post.has_audio,
        reply_count: post.text_post_app_info.direct_reply_count,
        like_count: post.like_count,
        images: post.carousel_media[].image_versions2.candidates[1].url,
        image_count: post.carousel_media_count,
        videos: post.video_versions[].url

    }""",
        data,
    )


    if result["reply_count"] and type(result["reply_count"]) != int:
        result["reply_count"] = int(result["reply_count"].split(" ")[0])

    if "videos" in result and result["videos"]:
        result["videos"] = list(set(result["videos"]))

    result["url"] = f"https://www.threads.net/@{result['username']}/post/{result['code']}"

    if "post" in data and "image_versions2" in data["post"]:  # Check if it's a single image post
        # Handle single image post outside of carousel_media
        post_image = data["post"]["image_versions2"]
        if "candidates" in post_image and post_image["candidates"]:
            result["images"] = [post_image["candidates"][0]["url"]]
        else:
            result["images"] = None  # No image URL found
    else:
        result["images"] = None  # No images case

    if result["images"]:
        downloaded_images = []
        for img_url in result["images"]:
            saved_path = download_image(img_url, image_save_path)
            if saved_path:
                downloaded_images.append(saved_path)
        result["images"] = downloaded_images  # 更新為本地圖片路徑
        result["image_count"] = len(result["images"])

    return result


async def scrape_thread(url: str) -> dict:
    """Scrape Threads post and replies from a given URL"""
    _xhr_calls = []
    result = await SCRAPFLY.async_scrape(
        ScrapeConfig(
            url,
            asp=True,  # enables scraper blocking bypass if any
            country="US",  # use US IP address as threads is only available in select countries
        )
    )
    hidden_datasets = result.selector.css(
        'script[type="application/json"][data-sjs]::text'
    ).getall()
    # find datasets that contain threads data
    for hidden_dataset in hidden_datasets:
        # skip loading datasets that clearly don't contain threads data
        if '"ScheduledServerJS"' not in hidden_dataset:
            continue
        if "thread_items" not in hidden_dataset:
            continue
        data = json.loads(hidden_dataset)
        # datasets are heavily nested, use nested_lookup to find
        # the thread_items key for thread data
        thread_items = nested_lookup("thread_items", data)
        if not thread_items:
            continue
        # use our jmespath parser to reduce the dataset to the most important fields
        threads = [parse_thread(t) for thread in thread_items for t in thread]
        return {
            "thread": threads[0:],
        }
    raise ValueError("could not find thread data in page")


# Example use:
if __name__ == "__main__":
    a = f"https://www.threads.net/@ni_.888"
    data = asyncio.run(scrape_thread(a))

    output_path = "./output_json"
    os.makedirs(output_path, exist_ok=True)
    output_file = os.path.join(output_path, f"data_{datetime.datetime.now(taipei_tz).strftime('%m%d_%H%M')}.json")

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    print(f"資料已保存到 {output_file}")