import asyncio
from BiliLink_main.quick_convert import quick_convert  # type: ignore

async  def main():
    url = input("请输入bilibili链接:")
    bilibili_url = await quick_convert(url)
    print("转换成功,公网链接为:")
    print(bilibili_url)

if __name__ == "__main__":
    asyncio.run(main())