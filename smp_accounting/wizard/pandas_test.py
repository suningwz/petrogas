import pandas as pd
import io
import xlsxwriter
import base64

text = 'kljkljllk'
file1 = 'test_1.xls'
file2 = 'test_2.xls'

df = pd.DataFrame([{'a': 1, 'b': 2}])

#***************************************************
# Method 1
#***************************************************
# io.TextIOBase()
# output = io.TextIOBase()
output = io.BytesIO()
# output = io.StringIO()
writer = pd.ExcelWriter(output, engine='xlsxwriter')
workbook = writer.book
df.to_excel('/home/disruptsol/Desktop/test_3.xls', sheet_name="details", index=False, startrow=6, startcol=0)
# df.to_excel(writer, sheet_name="details", index=False, startrow=6, startcol=0)
# workbook.close()
writer.save()
file = base64.encodebytes(output.getvalue())
output.close()

#***************************************************
# Method 2
#***************************************************
 # Create a Pandas dataframe from the data.
df = pd.DataFrame({'Data': [10, 20, 30, 20, 15, 30, 45]})

output = io.BytesIO()

# Use the BytesIO object as the filehandle.
writer = pd.ExcelWriter(output, engine='xlsxwriter')

# Write the data frame to the BytesIO object.
df.to_excel(writer, sheet_name='Sheet1')

writer.save()
xlsx_data = output.getvalue()
