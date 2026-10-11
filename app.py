import sys
from PyQt6.QtWidgets import (QApplication,
    QMainWindow, 
    QPushButton, 
    QLabel, 
    QVBoxLayout, 
    QHBoxLayout, 
    QWidget,
    QLineEdit,
    QDateTimeEdit)
from PyQt6.QtCore import QDateTime


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WeatherPy")
        self.resize(800,600)
        ParentLayout = QHBoxLayout()
        ParentWidget = QWidget()
        ParentWidget.setLayout(ParentLayout)
        ParentLayout.setSpacing(10)
        ParentLayout.setContentsMargins(5,5,5,5)
      

        self.UILayout = QVBoxLayout()

        
        #zip code entry box
        self.zipBox = QLineEdit()
        self.zipBox.setPlaceholderText("Enter a Zipcode")


        #timeframe entry (past 1 hour minimum)
        self.timeBox = QLabel("Enter the start and end time for the query\nThe default end time is now.")
        self.startTime = QDateTimeEdit()
        self.startTime.setDisplayFormat("MM/dd HH:mm")
        self.startTime.setDateTime(QDateTime.currentDateTime().addSecs(-3600))

        self.endTime = QDateTimeEdit()
        self.endTime.setDisplayFormat("MM/dd HH:mm")
        self.endTime.setDateTime(QDateTime.currentDateTime())
        self.endTime.setMaximumDateTime(QDateTime.currentDateTime())
        

        self.startTime.setMaximumDateTime(self.endTime.dateTime().addSecs(-3600))
        self.endTime.setMinimumDateTime(self.startTime.dateTime().addSecs(3600))
        self.endTime.dateTimeChanged.connect(self.update_start_limit)
        self.startTime.dateTimeChanged.connect(self.update_end_limit)


        


        #zip code submission button
        self.zipSubmit = QPushButton("Submit")

        self.UILayout.addWidget(self.zipBox)
        self.UILayout.addWidget(self.timeBox)
        self.UILayout.addWidget(self.startTime)
        self.UILayout.addWidget(self.endTime)
        self.UILayout.addWidget(self.zipSubmit)
        self.UILayout.addStretch()

       


        #add basic placeholder for images later
        self.RadarDisplay = QLabel()
        self.RadarDisplay.setMinimumWidth(300)
        self.RadarDisplay.setMinimumHeight(200)
        self.RadarDisplay.setStyleSheet("background-color: darkblue; border-radius: 5px;")
        self.rightLayout = QVBoxLayout(self.RadarDisplay)



        #assemble layout
        ParentLayout.addLayout(self.UILayout, stretch = 1)
        ParentLayout.addWidget(self.RadarDisplay, stretch=2)

        self.setCentralWidget(ParentWidget)

    def update_start_limit(self, newDateTime):
        self.startTime.setMaximumDateTime(newDateTime.addSecs(-3600))
    def update_end_limit(self, newDateTime):
        self.endTime.setMinimumDateTime(newDateTime.addSecs(3600))
app = QApplication(sys.argv)
w = MainWindow()
w.show()
app.exec()
