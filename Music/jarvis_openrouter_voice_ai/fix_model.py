with open('app.py','r',encoding='utf-8') as f: s=f.read()
s = s.replace(')[1]', ')[0]')
with open('app.py','w',encoding='utf-8') as f: f.write(s)
print('Fixed model to use ID.')
