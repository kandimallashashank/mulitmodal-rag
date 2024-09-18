import os
import re
import pdfkit
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import time

def setup_driver():
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.maximize_window()
    return driver

def get_all_article_links(base_url, driver):
    driver.get(base_url)
    last_height = driver.execute_script("return document.body.scrollHeight")
    
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)  # Wait for new content to load
        new_height = driver.execute_script("return document.body.scrollHeight")
        
        if new_height == last_height:
            break
        last_height = new_height

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    links = []
    for card in soup.find_all('div', class_='card-footer'):
        label = card.find('div', class_='label-grey')
        link = card.find_previous('a', href=True)
        if link:
            full_url = urljoin(base_url, link['href'])
            if label and 'Press Releases' in label.text:
                links.append((full_url, 'Press Releases'))
            else:
                links.append((full_url, 'News Releases'))
    return links

def download_and_convert_to_pdf(article_url, output_dir):
    try:
        os.makedirs(output_dir, exist_ok=True)
        pdf_filename = os.path.join(output_dir, f"{os.path.basename(article_url)}.pdf")
        pdfkit.from_url(article_url, pdf_filename, options={"enable-local-file-access": None})
        print(f"PDF saved: {pdf_filename}")
    except Exception as e:
        print(f"Error converting {article_url} to PDF: {str(e)}")

def process_articles():
    base_url = "https://www.maxlinear.com/news"
    news_dir = "./News_Releases"
    press_dir = "./Press_Releases"

    driver = setup_driver()
    article_links = get_all_article_links(base_url, driver)
    driver.quit()

    print(f"Found {len(article_links)} articles.")

    for index, (article_url, category) in enumerate(article_links):
        print(f"Processing article {index + 1}: {article_url} - Category: {category}")
        if category == 'Press Releases':
            download_and_convert_to_pdf(article_url, press_dir)
        else:
            download_and_convert_to_pdf(article_url, news_dir)

if __name__ == "__main__":
    process_articles()