import unittest
from datetime import datetime, timedelta, timezone
from lxml import html
from realtime_service.engine import classify

class ClassifierTests(unittest.TestCase):
 def setUp(self):
  self.node=html.fragment_fromstring("<div></div>")
  self.now=datetime.now(timezone.utc)
 def test_tilda_project_with_contact(self):
  x=classify("Требуется дизайнер для разработки лендинга на Tilda. Задача: 6-9 блоков. Проектная работа, оплата по договорённости. Контакт @design_customer",
   "https://t.me/test/1",self.node,"test",self.now)
  self.assertIsNotNone(x)
  self.assertEqual(x["category"],"web")
  self.assertEqual(x["contact"],"@design_customer")
 def test_presentation_project(self):
  x=classify("Срочно ищу дизайнера презентаций на 140 слайдов. Нужно оформить под один стиль. Оплата обсуждается, пишите @pitch_customer",
   "https://t.me/test/2",self.node,"test",self.now)
  self.assertIsNotNone(x);self.assertEqual(x["category"],"presentations")
 def test_no_contact(self):
  x=classify("Ищем дизайнера UI UX для разового проекта, пишите в комментариях",
   "https://t.me/test/3",self.node,"test",self.now)
  self.assertIsNone(x)
 def test_old_post(self):
  x=classify("Требуется дизайнер для лендинга Tilda, проектная работа, @customer_2026",
   "https://t.me/test/4",self.node,"test",self.now-timedelta(days=4))
  self.assertIsNone(x)
 def test_self_promotion(self):
  x=classify("Я дизайнер ищу проекты и заказы. Разработаю сайт, UI/UX и презентации. Мой контакт @portfolio_sales",
   "https://t.me/test/5",self.node,"test",self.now)
  self.assertIsNone(x)
 def test_multiple_ads_in_one_post(self):
  x=classify("1. #Вебдизайнер Ищем сайт, @oneclient 2. #Презентации Ищем презентацию @secondclient",
   "https://t.me/test/6",self.node,"rueventjob",self.now)
  self.assertIsNone(x)
 def test_ordinary_job(self):
  x=classify("Вакансия UI/UX дизайнера в штат компании. Полная занятость, оклад. Пишите @hr_design",
   "https://t.me/test/7",self.node,"test",self.now)
  self.assertIsNone(x)

if __name__=="__main__":unittest.main()
