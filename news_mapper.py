import re
from datetime import datetime
import spacy
from spacy.tokens import Span
from spacy.matcher import Matcher
from opencage.geocoder import OpenCageGeocode
nlp = spacy.load("en_core_web_sm")
from newsapi import NewsApiClient
from newspaper import Article
from datetime import datetime, timedelta
import csv
import dateparser
import os
from gensim.summarization.summarizer import summarize
newsapikey = None
geocodeapikey = None
with open(os.environ['USERPROFILE']+"\\Documents\\private\\newsapikey.txt", "r") as f:
    newsapikey = f.read()
with open(os.environ['USERPROFILE']+"\\Documents\\private\\geocodeapikey.txt", "r") as f:
    geocodeapikey = f.read()

def create_search(countries, keywords, all_countries=True, all_keywords=False):
    search = "("
    for country in countries:
        search+=country
        if all_countries:
            search +=" AND "
        else:
            search+=" OR "
    search = re.sub(r" (OR|AND) $", ' ', search)
    search+=") AND ("

    for word in keywords:
        search+=word
        if all_keywords:
            search+=" AND "
        else:
            search+=" OR "
    search = re.sub(r" (OR|AND) $", ' ', search)
    search+=")"
    search = re.sub(r" \)", ')', search)
    return search


def geocalc(location):
    geocoder = OpenCageGeocode(geocodeapikey)
    try:
        results = geocoder.geocode(location)

        return results[0]['geometry']['lat'], results[0]['geometry']['lng']
    except:
        pass
    return None, None


def get_news(countries, keywords, from_time, current_time):
    newsapi = NewsApiClient(api_key=newsapikey)
    #future
    synonyms = False
    # save last current time to file, read that to build param to - should alwaus be todays date

    articles = newsapi.get_everything(q=create_search(countries, keywords),
                                     from_param=from_time, to=current_time,
                                     page_size=100)


    return articles

def find_matches(text, keywords, countries):
    all_matches = []
    country_reg_string = "((?:"
    for c in countries:
         country_reg_string+=c.lower()+"|"
    country_reg_string = country_reg_string.rstrip("|")
    country_reg_string +=")(?:\\')?\w+)"
    doc_sent = nlp(text)
    for sent in doc_sent.sents:
        doc = nlp(sent.text)

        def on_match(matcher, doc, id, matches):
            country = None
            location = None
            date = None
            for m in matches:
                num, start, end = m
            keyword = nlp.vocab.strings[num]
            for ent in doc[start:end].ents:
                if ent.label_ == 'GPE' or ent.label_ == 'NORP':
                    for coun in countries:
                        if coun.lower() in ent.text.lower():
                            country = coun
                            break
                if ent.label_ == 'LOC':
                    location = re.sub(r'^the ', '', ent.text.strip(), flags=re.IGNORECASE)

                if ent.label_ == 'DATE':
                    date = ent.text.strip()
            if country != None and location != None:
                value = {"country":country, "event":keyword, "location":location, "sentence":str(sent.text).strip()}
                if date != None:
                    value['date'] = date
                if value not in all_matches:
                    all_matches.append(value)

                    print(doc[start:end])
        matcher = Matcher(nlp.vocab)

        for c in countries:
            for entity_i in keywords:
                if " " in entity_i:
                    pre_build = [{"NORM":{"REGEX":country_reg_string}}, {"OP":"*"}]
                    for i in entity_i.split(" "):
                        pre_build.append({"NORM":i})
                    pre_build.append({"OP":"*"})
                    pre_build.append({"TAG":"IN"})
                    pre_build.append({"OP":"*"})
                    pre_build.append({"ENT_TYPE":"LOC"})
                    matcher.add(entity_i, on_match, pre_build)
                else:
                    matcher.add(entity_i, on_match, [{"NORM":{"REGEX":country_reg_string}}, {"OP":"*"}, {"NORM":entity_i}, {"OP":"*"}, {"TAG":"IN"},{"OP":"*"},{"ENT_TYPE":"LOC"}])

        matches = matcher(doc)
    return list(all_matches)


def article_pull(articles, countries, keywords):
    print("number of articles: ", len(articles["articles"]))
    if len(articles["articles"]) > 0:

        for section in articles["articles"]:
            try:
                article = Article(section['url'].replace("theguardian.comworld/", 'theguardian.com/world/'))
                article.download()
                article.parse()
                possible_matches = find_matches(article.text, keywords, countries)
                section["matches"]=possible_matches
                section["full_body"] = article.text
            except Exception as e:
                print(e)
                pass
    else:
        print("nothing new here")
    care_about = []
    for section in articles["articles"]:
        try:
            if section['matches'] != []:
                care_about.append(section)
        except:
            continue

    days_of_week = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    for ca in care_about:
        for m in ca['matches']:
            m['lat'], m['lng'] = geocalc(m['location'])
            if 'date' not in m.keys():
                doc = nlp(ca['full_body'])
                for ent in doc.ents:
                    if ent.label_ == 'DATE':
                        m['date'] = ent.text.strip()
                        break
            if 'date' in m.keys():
                if m['date'].lower() in days_of_week:
                    day = None
                    c = 0
                    while c < len(days_of_week):
                        if days_of_week[c] == m['date'].lower():
                            day = c
                            break
                        c+=1
                    if day != None:
                        counter = 0
                        while counter < 7:
                            try:
                                check = datetime.strptime(ca['publishedAt'], '%Y-%m-%dT%H:%M:%SZ') - timedelta(days=counter)
                                if check.weekday() == day:
                                    print("successful date conversion: ",m['date'])
                                    m['date'] = check.strftime('%B %d, %Y')
                                    print("to: ", m['date'])
                                    break
                            except Exception as e:
                                print(e)
                                pass
                            counter +=1
    return care_about


def write_to_file(data, save_location='document\\tracker.csv'):
    with open(save_location, 'a', newline='') as f:
        writer = csv.writer(f)

        for section in data:
            try:
                summary = summarize(section['full_body'], word_count = 125)
                clean_date = dateparser.parse(section['matches'][0]['date'])
                create_name = clean_date.strftime('%b. %d')+" - "+section['matches'][0]['location']
                create_description = "("+clean_date.strftime('%B %d, %Y')+") "+summary
                writer.writerow([create_name, clean_date.strftime('%B %d, %Y'), section['matches'][0]['location'], section['matches'][0]['lat'], section['matches'][0]['lng'], create_description, section['source']['name'], section['url']])
            except Exception as e:
                print(e)
                pass


if __name__ == '__main__':
    now = datetime.now()
    current_time = now.strftime('%Y-%m-%dT%H:%M:%S')

    with open('config\\last_date.txt', 'r') as f:
        from_time = f.read()
    countries = ['Russia']
    keywords = [['air force', 'missile intercept', 'aircraft', 'intercept', 'NATO intercept', 'jet',  'warplane', 'helicopter'],
    ['warship', 'submarine', 'vessel', 'cruiser', 'ship', 'battle ship', 'battleship', 'navy'],
    ['ground troops', 'army', 'ground movements', 'ground forces', 'military', 'bombed', 'bombing']]
    for ks in keywords:
        articles = get_news(countries, ks, from_time, current_time)
        of_interest = article_pull(articles, countries, ks)
        write_to_file(of_interest)
    with open('config\\last_date.txt', 'w') as f:
        f.write(current_time)
