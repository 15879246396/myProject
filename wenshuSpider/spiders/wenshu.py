# -*- coding: utf-8 -*-
import scrapy
import re
import json
import time
import execjs
from scrapy import FormRequest, Request
from wenshuSpider import setting
from wenshuSpider.items import WenshuspiderItem


class WenshuSpider(scrapy.Spider):
    name = 'wenshu'
    allowed_domains = ['wenshu.court.gov.cn']
    start_urls = ['http://wenshu.court.gov.cn/Index']

    def start_request(self):
        court_list = setting.COURT_LIST
        for court_name in court_list:
            print(court_name)
            guid = self.get_guid()
            post_url = 'http://wenshu.court.gov.cn/ValiCode/GetCode'
            yield FormRequest(post_url,
                              formdata={'guid': guid},
                              callback=self.get_number,
                              meta={'guid': guid,
                                    'court': court_name},
                              dont_filter=True)

    def get_number(self, response):
        # print(response.body)
        # 向list/list发请求，获取cookie里的vjkl5
        court_name = response.meta['court']
        number = response.body.decode()
        guid = response.meta['guid']
        get_url = 'http://wenshu.court.gov.cn/list/list/?sorttype=1&&number='
        get_url += number + '&guid=' + guid + 'conditions=searchWord+' + \
            court_name + '+SLFY++法院名称:' + court_name
        yield Request(get_url,
                      callback=self.get_vl5x,
                      dont_filter=True,
                      meta={'guid': guid,
                            'court': court_name,
                            'number': number})

    def get_vl5x(self, response):
        court_name = response.meta['court']
        number = response.meta['number']
        guid = response.meta['guid']
        # 提取vjkl5,转为vl5x，发送请求
        cookie = response.headers.getlist('Set-Cookie')
        if len(cookie) == 1:
            vjkl5 = re.findall('vjkl5=(.*?);', cookie[0].decode())
            if len(vjkl5) == 1:
                vjkl5 = vjkl5[0]
                # print (vjkl5, number)
                jsstr = self.get_js('getKey.js')
                ctx = execjs.compile(jsstr)
                vl5x = ctx.call('getKey', vjkl5)
                data = {
                    "Param": '法院名称:' + court_name,
                    "Index": "1",
                    "Page": "5",
                    "Order": "法院层级",
                    "Direction":
                    "asc",
                    "vl5x": vl5x,
                    "number": number,
                    "guid": guid}
                post_url = 'http://wenshu.court.gov.cn/List/ListContent'
                header = {
                    'Cookie': ['vjkl5=' + vjkl5, ],
                }
                yield FormRequest(post_url,
                                  formdata=data,
                                  callback=self.get_total_old,
                                  dont_filter=True,
                                  headers=header,
                                  meta={'vl5x': vl5x,
                                        'court': court_name,
                                        'guid': guid,
                                        'number': number,
                                        'vjkl5': vjkl5})

    def get_total_old(self, response):
        # print(response.body.decode())
        court_name = response.meta['court']
        number = response.meta['number']
        guid = response.meta['guid']
        vl5x = response.meta['vl5x']
        vjkl5 = response.meta['vjkl5']
        body_text = response.body.decode().replace("\\", "")
        try:
            dict_text = json.loads(body_text[1:-1])
        except:
            dict_text = ""
        if dict_text:
            try:
                full_num = int(dict_text[0]["Count"])
                if full_num % 20 == 0:
                    loop_time = full_num // 20
                else:
                    loop_time = full_num // 20 + 1
                for page_index in range(1, loop_time + 1):
                    if page_index <= 100:
                        data = {
                            "Param": '法院名称:' + court_name,
                            "Index": str(page_index),
                            "Page": "20",
                            "Order": "法院层级",
                            "Direction": "asc",
                            "vl5x": vl5x,
                            "number": number,
                            "guid": guid,
                        }
                        header = {
                            'Cookie': ['vjkl5=' + vjkl5],
                        }
                        post_url = 'http://wenshu.court.gov.cn/\
                                    List/ListContent'
                        yield FormRequest(post_url,
                                          formdata=data,
                                          callback=self.get_DocID,
                                          dont_filter=True,
                                          headers=header,
                                          meta={'vjkl5': vjkl5})
            except:
                pass

    def get_DocID(self, response):
        body_text = response.body.decode().replace("\\", "")
        try:
            dict_text = json.loads(body_text[1:-1])
            RunEval = dict_text[0]['RunEval']
        except:
            dict_text = ""
        if dict_text:
            id_num = len(dict_text)
            htmlstr = self.get_js('get_DocID.js')
            ex = execjs.compile(htmlstr)
            for id_index in range(1, id_num):
                book_id_key = dict_text[id_index]['文书ID']
                book_id = ex.call('get_ID', RunEval, book_id_key)
                case_num = dict_text[id_index]['案号']
                date_text = dict_text[id_index]['裁判日期']
                title = dict_text[id_index]['案件名称']
                doc_type = dict_text[id_index]["案件类型"]
                court = dict_text[id_index]["法院名称"]
                url = "http://wenshu.court.gov.cn/\
                      CreateContentJS/CreateContentJS.aspx?DocID=" + book_id
                print(url)
                yield Request(url,
                              meta={"date_text": date_text,
                                    "title": title,
                                    "case_num": case_num,
                                    "doc_type": doc_type,
                                    "court": court},
                              callback=self.parse,
                              dont_filter=True)

    def parse(self, response):
        temp = response.xpath("/html/body/div//text()").extract()
        if not temp:
            req = response.request
            req.meta["change_proxy"] = True
            return req
        else:
            type_list = {"1": u"刑事", "2": u"民事", "3": u"行政", "4": u"赔偿"}
            date_text = response.meta['date_text']
            title = response.meta['title']
            case_num = response.meta['case_num']
            doc_type = response.meta['doc_type']
            court = response.meta['court']
            news = WenshuspiderItem()
            news['date'] = date_text
            news['title'] = title.replace(u"xa0", " ").replace(u"\u3000", " ")
            news["link"] = response.url
            # 案号
            news['casenum'] = case_num.strip()
            # 查询日期
            news['querydate'] = time.strftime('%Y-%m-%d', time.localtime())
            if doc_type in type_list:
                news['doctype'] = type_list[doc_type]
            else:
                news['doctype'] = ""
            temp = response.xpath("/html/body/div//text()").extract()
            content = ''
            if temp:
                for te in temp:
                    content += " " + \
                        te.replace('"', '').replace(
                            '\\', '').replace('    ', '').strip()
                news['text'] = content.strip().replace('\r\n', '').replace('"', '').replace(' ', '').replace('\\',
                                                                                                             '').replace(
                    '\n', '').replace(u"xa0", " ").replace(u"\u3000", " ").strip()
            else:
                news['text'] = ''

            news['court'] = court.replace(
                u"xa0", " ").replace(u"\u3000", " ").strip()
            # 审判员
            temp = response.xpath("/html/body/div")
            judge = ""
            for tr_index in range(len(temp) - 1, -1, -1):
                tr_text = temp[tr_index].xpath(".//text()").extract()
                judge_text = "".join(tr_text).replace(u"\xa0", "").replace("\r\n", "").replace("\n", "").replace("\t",
                                                                                                                 "").replace(
                    " ", "").strip()
                judge = re.findall(u"审判长.+", judge_text)
                if judge:
                    judge = judge[0]
                    break
            if judge:
                news['judge'] = judge
            else:
                judge2 = ""
                for tr_index in range(len(temp) - 1, -1, -1):
                    tr_text = temp[tr_index].xpath(".//text()").extract()
                    judge2_text = "".join(tr_text).replace(u"\xa0", "").replace("\r\n", "").replace("\n", "").replace(
                        "\t", "").replace(" ", "").strip()
                    judge2 = re.findall(u"审判员.+", judge2_text)
                    if judge2:
                        judge2 = judge2[0]
                        break
                if judge2:
                    news['judge'] = judge2
                else:
                    judge3 = ""
                    for tr_index in range(len(temp) - 1, -1, -1):
                        tr_text = temp[tr_index].xpath(".//text()").extract()
                        judge3_text = "".join(tr_text).replace(u"\xa0", "").replace("\r\n", "").replace("\n",
                                                                                                        "").replace(" ",
                                                                                                                    "").replace(
                            "\t",
                            "").strip()
                        judge3 = re.findall(u"代理审判员.+", judge3_text)
                        if judge3:
                            judge3 = judge3[0]
                            break
                    if judge3:
                        news['judge'] = judge3
                    else:
                        news['judge'] = ""
            news['judge'] = news['judge'].replace(
                u"xa0", " ").replace(u"\u3000", " ")
            # 原告
            plaintiffset = set()
            rel_plaintiffset = set()
            up_check = ""
            app_check = ""
            if temp:
                plaintiff_content = content.replace('\n', '').replace("\r\n", "").replace("\t", "").replace(u"\xa0",
                                                                                                            "").replace(
                    u' ', '').replace(case_num, u'。').replace(u'，', '\n').replace(u'。', '\n').replace(u',',
                                                                                                      '\n').replace(
                    u'\.', '\n').replace(u"：", ":")

                plaintiff_info = re.findall(u"\\n原告人:(.+)", plaintiff_content)
                if not plaintiff_info:
                    plaintiff_info = re.findall(
                        u"\\n原告人(.+)", plaintiff_content)
                if not plaintiff_info:
                    plaintiff_info = re.findall(
                        u"\\n原告:(.+)", plaintiff_content)
                if not plaintiff_info:
                    plaintiff_info = re.findall(
                        u"\\n原告(.+)", plaintiff_content)

                if re.findall(u"号原告(.+)", plaintiff_content):
                    for n in re.findall(u"号原告(.+)", plaintiff_content):
                        plaintiff_info.append(n)
                if re.findall(u"号原告人(.+)", plaintiff_content):
                    for n in re.findall(u"号原告人(.+)", plaintiff_content):
                        plaintiff_info.append(n)
                # 上述人
                if re.findall(u"\\n上诉人（.*?）(.+)", plaintiff_content):
                    up_check = "1"
                    for n in re.findall(u"\\n上诉人（.*?）(.+)", plaintiff_content):
                        plaintiff_info.append(n)
                elif re.findall(u"\\n上诉人(.+)", plaintiff_content):
                    up_check = "1"
                    for n in re.findall(u"\\n上诉人(.+)", plaintiff_content):
                        plaintiff_info.append(n)
                # 申请执行人，申请人
                if re.findall(u"\\n[一 二 三 四 再 终]{0,1}[审]{0,1}申请人（.*?）(.+)", plaintiff_content):
                    app_check = "1"
                    for n in re.findall(u"\\n[一 二 三 四 再 终]{0,1}[审]{0,1}申请人（.*?）(.+)", plaintiff_content):
                        plaintiff_info.append(n)
                elif re.findall(u"\\n[一 二 三 四 再 终]{0,1}[审]{0,1}申请人(.+)", plaintiff_content):
                    app_check = "1"
                    for n in re.findall(u"\\n[一 二 三 四 再 终]{0,1}[审]{0,1}申请.*人(.+)", plaintiff_content):
                        plaintiff_info.append(n)
                for plaintiff in plaintiff_info:
                    plaint_long = re.findall(
                        plaintiff.replace("(", "\(").replace(")", "\)").replace("*", "\*").replace(".",
                                                                                                   "\.").replace(
                            "^", "\^"), plaintiff_content)
                    if len(plaint_long) >= 1:
                        plaintiffset.add(plaintiff)
                        rel_plaintiffset.add(plaintiff)
            for i in plaintiffset:
                for j in plaintiffset:
                    if j == i:
                        pass
                    else:
                        if len(re.findall(
                                j.replace(u"（", "").replace(u"）", "").replace(u"：", "").replace("(", "").replace(")",
                                                                                                                 "").replace(
                                    ":", ""), i)) > 0:
                            if i in rel_plaintiffset:
                                rel_plaintiffset.remove(i)
            if not plaintiffset:
                rel_plaintiffset.add('')
            plaintiffs = ''
            for name in rel_plaintiffset:
                # print (name)
                plaintiffs = plaintiffs + name.replace(u"（", "").replace(u"）", "").replace(u"：", "").replace("(",
                                                                                                             "").replace(
                    ")", "").replace(":", "").replace(u"xa0", " ").replace(u"\u3000", " ") + ","
            news['plaintiff'] = plaintiffs[:-1]
            # 被告，被上诉人，被执行人，被申请人
            defendantset = set()
            rel_defendantset = set()
            if temp:
                defendant_info = []
                defendant_content = content.replace('\n', '').replace("\r\n", "").replace("\t", "").replace(u"\xa0",
                                                                                                            "").replace(
                    u' ', '').replace(case_num, u'。').replace(u'，', '\n').replace(u'。', '\n').replace(u',',
                                                                                                      '\n').replace(
                    u'\.', '\n').replace(u"：", ":")
                if re.findall(u"\\n罪犯(.+)", defendant_content):
                    for n in re.findall(u"\\n罪犯(.+)", defendant_content):
                        defendant_info.append(n)
                elif up_check:
                    # 被上述人
                    if re.findall(u"被上诉人（.*?）(.+)", defendant_content):
                        for n in re.findall(u"被上诉人（.*?）(.+)", defendant_content):
                            defendant_info.append(n)
                    elif re.findall(u"被上诉人(.+)", defendant_content):
                        for n in re.findall(u"被上诉人(.+)", defendant_content):
                            defendant_info.append(n)
                elif app_check:
                    if re.findall(u"\\n被申请人（.*?）(.+)", defendant_content):
                        defendant_info.append(re.findall(
                            u"\\n被申请人（.*?）(.+)", defendant_content)[0])
                    elif re.findall(u"\\n被申请人(.+)", defendant_content):
                        defendant_info.append(re.findall(
                            u"\\n被申请人(.+)", defendant_content)[0])
                else:
                    defendant_info = re.findall(
                        u"\\n被告人:(.+)", defendant_content)
                    if not defendant_info:
                        defendant_info = re.findall(
                            u"\\n被告人(.+)", defendant_content)
                    if not defendant_info:
                        defendant_info = re.findall(
                            u"\\n被告:(.+)", defendant_content)
                    if not defendant_info:
                        defendant_info = re.findall(
                            u"\\n被告(.+)", defendant_content)
                    # 被执行人
                    if re.findall(u"被执行人(.+)", defendant_content):
                        for n in re.findall(u"被执行人(.+)", defendant_content):
                            defendant_info.append(n)

                for defendant in defendant_info:
                    s = defendant.replace("(", "\(").replace(")", "\)").replace("*", "\*").replace(".", "\.").replace("^", "\^")
                    if len(re.findall(s, defendant_content)) > 1:
                        defendantset.add(defendant)
                        rel_defendantset.add(defendant)
            for i in defendantset:
                for j in defendantset:
                    if j == i:
                        pass
                    else:
                        defendant_long = re.findall(j.replace(":", ""), i)
                        if len(defendant_long) > 0:
                            if i in rel_defendantset:
                                rel_defendantset.remove(i)
                            else:
                                pass
            if not defendantset:
                rel_defendantset.add('')
            # log.msg(': '.join([response.url, news['title']]), level=log.INFO)
            defendant_final = ""
            for name in defendantset:
                defendant_final += name.replace(u"（", "").replace(u"）", "").replace(u"：", "").replace("(", "").replace(
                    ")", "").replace(":", "").replace(u"xa0", " ").replace(u"\u3000", " ") + ","
            news['defendant'] = defendant_final[:-1]
            return news

    def get_guid(self):
        return self.guid() + self.guid() + "-" + \
            self.guid() + "-" + self.guid() + self.guid() + "-" + \
            self.guid() + self.guid() + self.guid()

    def get_js(self, js_name):
        js_path = setting.JS_PATH + js_name
        f = open(js_path, 'r')
        line = f.readline()
        htmlstr = ''
        while line:
            htmlstr += line
            line = f.readline()
        f.close()
        return htmlstr
