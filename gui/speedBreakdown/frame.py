# =============================================================================
# Copyright (C) 2010 Diego Duclos
#
# This file is part of pyfa.
#
# pyfa is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# pyfa is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with pyfa.  If not, see <http://www.gnu.org/licenses/>.
# =============================================================================

import csv
# noinspection PyPackageRequirements
import wx

import gui.globalEvents as GE
import gui.mainFrame
from gui.auxWindow import AuxiliaryFrame
from service.fit import Fit
from service.speedBreakdown import get_speed_breakdown

_t = wx.GetTranslation


def _fmt_speed(v):
    if v is None:
        return "—"
    return "{:.1f}".format(v)


def _fmt_range(v):
    if v is None:
        return "—"
    return "{:.1f}".format(v / 1000.0)


# Cargo list columns
COL_CARGO_NAME = 0
COL_CARGO_TYPE = 1


class SpeedBreakdownFrame(AuxiliaryFrame):

    def __init__(self, parent):
        super().__init__(parent, title=_t('Speed Breakdown'), size=(720, 420), resizeable=True)
        self.mainFrame = gui.mainFrame.MainFrame.getInstance()
        self._data = None  # dict from get_speed_breakdown or None

        mainSizer = wx.BoxSizer(wx.VERTICAL)

        # Fitted ship section
        fittedBox = wx.StaticBoxSizer(wx.VERTICAL, self, _t('Fitted ship'))
        fittedPropSizer = wx.BoxSizer(wx.HORIZONTAL)
        fittedPropSizer.Add(wx.StaticText(self, wx.ID_ANY, _t('Fitted prop:') + ' '), 0)
        self.fittedPropLabel = wx.StaticText(self, wx.ID_ANY, "—")
        fittedPropSizer.Add(self.fittedPropLabel, 0)
        fittedBox.Add(fittedPropSizer, 0, wx.ALL, 5)
        # Table: Base speed, AB speed, MWD speed, Lock range | No boost | With boost
        grid = wx.FlexGridSizer(5, 3, 4, 4)
        grid.AddGrowableCol(1, 1)
        grid.AddGrowableCol(2, 1)
        # Header row
        grid.Add(wx.StaticText(self, wx.ID_ANY, ""), 0)
        grid.Add(wx.StaticText(self, wx.ID_ANY, _t('No boost')), 0, wx.ALIGN_CENTER)
        grid.Add(wx.StaticText(self, wx.ID_ANY, _t('With boost')), 0, wx.ALIGN_CENTER)
        # Base speed row
        grid.Add(wx.StaticText(self, wx.ID_ANY, _t('Base speed (m/s)')), 0)
        self.speedBaseNoBoost = wx.StaticText(self, wx.ID_ANY, "—")
        self.speedBaseWithBoost = wx.StaticText(self, wx.ID_ANY, "—")
        grid.Add(self.speedBaseNoBoost, 0, wx.ALIGN_CENTER)
        grid.Add(self.speedBaseWithBoost, 0, wx.ALIGN_CENTER)
        # AB speed row
        grid.Add(wx.StaticText(self, wx.ID_ANY, _t('AB speed (m/s)')), 0)
        self.speedABNoBoost = wx.StaticText(self, wx.ID_ANY, "—")
        self.speedABWithBoost = wx.StaticText(self, wx.ID_ANY, "—")
        grid.Add(self.speedABNoBoost, 0, wx.ALIGN_CENTER)
        grid.Add(self.speedABWithBoost, 0, wx.ALIGN_CENTER)
        # MWD speed row
        grid.Add(wx.StaticText(self, wx.ID_ANY, _t('MWD speed (m/s)')), 0)
        self.speedMWDNoBoost = wx.StaticText(self, wx.ID_ANY, "—")
        self.speedMWDWithBoost = wx.StaticText(self, wx.ID_ANY, "—")
        grid.Add(self.speedMWDNoBoost, 0, wx.ALIGN_CENTER)
        grid.Add(self.speedMWDWithBoost, 0, wx.ALIGN_CENTER)
        # Lock range row
        grid.Add(wx.StaticText(self, wx.ID_ANY, _t('Lock range (km)')), 0)
        self.lockNoBoost = wx.StaticText(self, wx.ID_ANY, "—")
        self.lockWithBoost = wx.StaticText(self, wx.ID_ANY, "—")
        grid.Add(self.lockNoBoost, 0, wx.ALIGN_CENTER)
        grid.Add(self.lockWithBoost, 0, wx.ALIGN_CENTER)
        fittedBox.Add(grid, 0, wx.ALL, 5)
        mainSizer.Add(fittedBox, 0, wx.EXPAND | wx.ALL, 5)

        # Cargo propulsion section (hidden when no cargo prop rows)
        self.cargoBox = wx.StaticBoxSizer(wx.VERTICAL, self, _t('Propulsion in cargo'))
        self.cargoList = wx.ListCtrl(
            self, wx.ID_ANY,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN
        )
        self.cargoList.AppendColumn(_t('Item'), wx.LIST_FORMAT_LEFT, 220)
        self.cargoList.AppendColumn(_t('Type'), wx.LIST_FORMAT_LEFT, 120)
        self.cargoBox.Add(self.cargoList, 1, wx.EXPAND | wx.ALL, 5)
        mainSizer.Add(self.cargoBox, 1, wx.EXPAND | wx.ALL, 5)

        self.emptyLabel = wx.StaticText(self, wx.ID_ANY, _t('No fit loaded.'))
        self.emptyLabel.Hide()
        mainSizer.Add(self.emptyLabel, 0, wx.ALL, 10)

        btnSizer = wx.BoxSizer(wx.HORIZONTAL)
        self.exportBtn = wx.Button(self, wx.ID_ANY, _t('Export…'))
        self.exportBtn.Bind(wx.EVT_BUTTON, self.OnExport)
        btnSizer.Add(self.exportBtn, 0, wx.RIGHT, 5)
        self.copyBtn = wx.Button(self, wx.ID_ANY, _t('Copy to clipboard'))
        self.copyBtn.Bind(wx.EVT_BUTTON, self.OnCopyToClipboard)
        btnSizer.Add(self.copyBtn, 0)
        mainSizer.Add(btnSizer, 0, wx.ALL, 5)

        self.SetSizer(mainSizer)

        self.mainFrame.Bind(GE.FIT_CHANGED, self.OnFitChanged)
        self.Bind(wx.EVT_CLOSE, self.OnClose)

        self.refresh()

    def _get_fit(self):
        fitID = self.mainFrame.getActiveFit()
        if fitID is None:
            return None
        return Fit.getInstance().getFit(fitID)

    def refresh(self):
        fit = self._get_fit()
        if fit is None:
            self._data = None
            self._show_empty()
            self.Layout()
            return
        self._data = get_speed_breakdown(fit)
        self._populate()
        self.Layout()

    def _show_empty(self):
        self.fittedPropLabel.SetLabel("—")
        self.speedBaseNoBoost.SetLabel("—")
        self.speedBaseWithBoost.SetLabel("—")
        self.speedABNoBoost.SetLabel("—")
        self.speedABWithBoost.SetLabel("—")
        self.speedMWDNoBoost.SetLabel("—")
        self.speedMWDWithBoost.SetLabel("—")
        self.lockNoBoost.SetLabel("—")
        self.lockWithBoost.SetLabel("—")
        self.cargoList.DeleteAllItems()
        self.cargoBox.GetStaticBox().Hide()
        self.cargoList.Hide()
        self.emptyLabel.Show()
        self.exportBtn.Enable(False)
        self.copyBtn.Enable(False)

    def _populate(self):
        d = self._data
        self.emptyLabel.Hide()
        self.fittedPropLabel.SetLabel(d.get('fittedPropLabel') or "—")
        # Base speed = no prop
        self.speedBaseNoBoost.SetLabel(_fmt_speed(d['speedNoPropNoBoost']))
        self.speedBaseWithBoost.SetLabel(_fmt_speed(d['speedNoPropWithBoost']))
        # AB / MWD rows: from fitted prop or simulated from cargo
        self.speedABNoBoost.SetLabel(_fmt_speed(d.get('speedWithABNoBoost')))
        self.speedABWithBoost.SetLabel(_fmt_speed(d.get('speedWithABWithBoost')))
        self.speedMWDNoBoost.SetLabel(_fmt_speed(d.get('speedWithMWDNoBoost')))
        self.speedMWDWithBoost.SetLabel(_fmt_speed(d.get('speedWithMWDWithBoost')))
        self.lockNoBoost.SetLabel(_fmt_range(d['lockRangeNoBoost']))
        self.lockWithBoost.SetLabel(_fmt_range(d['lockRangeWithBoost']))
        self.cargoList.DeleteAllItems()
        for row in d['cargoPropRows']:
            idx = self.cargoList.InsertItem(self.cargoList.GetItemCount(), row['name'])
            self.cargoList.SetItem(idx, COL_CARGO_TYPE, row['propType'])
        if d['cargoPropRows']:
            self.cargoBox.GetStaticBox().Show()
            self.cargoList.Show()
        else:
            self.cargoBox.GetStaticBox().Hide()
            self.cargoList.Hide()
        self.exportBtn.Enable(True)
        self.copyBtn.Enable(True)

    def OnFitChanged(self, event):
        event.Skip()
        self.refresh()

    def OnClose(self, event):
        self.mainFrame.Unbind(GE.FIT_CHANGED, handler=self.OnFitChanged)
        event.Skip()

    def _get_csv_content(self):
        lines = []
        d = self._data
        if d is None:
            return lines
        lines.append(["", _t('No boost'), _t('With boost')])
        lines.append([_t('Base speed (m/s)'), _fmt_speed(d['speedNoPropNoBoost']), _fmt_speed(d['speedNoPropWithBoost'])])
        lines.append([_t('AB speed (m/s)'), _fmt_speed(d.get('speedWithABNoBoost')), _fmt_speed(d.get('speedWithABWithBoost'))])
        lines.append([_t('MWD speed (m/s)'), _fmt_speed(d.get('speedWithMWDNoBoost')), _fmt_speed(d.get('speedWithMWDWithBoost'))])
        lines.append([_t('Lock range (km)'), _fmt_range(d['lockRangeNoBoost']), _fmt_range(d['lockRangeWithBoost'])])
        if d['cargoPropRows']:
            lines.append([])
            lines.append([_t('Item'), _t('Type')])
            for row in d['cargoPropRows']:
                lines.append([row['name'], row['propType']])
        return lines

    def OnExport(self, event):
        if self._data is None:
            return
        fit = self._get_fit()
        defaultFile = 'speed_breakdown.csv'
        if fit and fit.ship and fit.ship.item:
            defaultFile = '{} - speed_breakdown.csv'.format(fit.ship.item.name.replace('/', '-'))
        with wx.FileDialog(
                self, _t('Export speed breakdown'), '', defaultFile,
                _t('CSV files') + ' (*.csv)|*.csv', wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, delimiter=',')
            for line in self._get_csv_content():
                writer.writerow(line)
        event.Skip()

    def OnCopyToClipboard(self, event):
        if self._data is None:
            return
        lines = self._get_csv_content()
        text = '\n'.join(','.join(str(c) for c in row) for row in lines)
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Close()
        event.Skip()
