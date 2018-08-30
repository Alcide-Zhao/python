"""
This is to plot the TS  from the EDGAR six experiments
data inputs are forty years of monthly TS
	first step is to process the monthly TS into monthly mean
	second step is to process annual mean of monthly mean
"""
import site
import os
import numpy as np
import netCDF4 as nc4
from scipy import stats
import scipy.io as sio
import math
import matplotlib.pyplot as plt
from scipy.interpolate import interp2d  as interp2d
from scipy.stats import mannwhitneyu as man_test
from scipy.stats import ttest_ind as student_test

lib_path = os.path.join(
    os.path.realpath(
        os.path.dirname(__file__)
    ), 
    os.path.pardir,os.path.pardir,os.path.pardir,
)
site.addsitedir(lib_path)
from lib import *

def spatial_figure(axs,data,p_value,lons,lats,colormap,colorbar_min,colorbar_max,tb_lef=True,tb_bot=True): #c_bad,c_under,c_over,c_number=20,
	def plot_rectangle(bmap, lonmin,lonmax,latmin,latmax):
		xs = [lonmin,lonmax,lonmax,lonmin,lonmin]
		ys = [latmin,latmin,latmax,latmax,latmin]
		bmap.plot(xs, ys,latlon = True,linewidth = 2,color='k')
	
	"""
	input : all parameters and data rel;ated to the figure you want to plot_title
	output : a spatial map of the data
	"""
	lons[lons>180]-=360; 
	# calculate the origin of the map
	lon_0 = lons.mean(); 
	lat_0 = lats.mean(); 
	
	lon_b = np.min(lons); lon_e = np.max(lons)
	lat_b = np.min(lats); lat_e = np.max(lats)	
	lon_bin = 60; lat_bin = 30
	map = Basemap(lat_0=0, lon_0=0,llcrnrlon=lon_b,llcrnrlat=lat_b,urcrnrlon=lon_e,urcrnrlat=lat_e,ax=axs,projection='cyl')
	lon, lat = np.meshgrid(lons, lats)
	xi, yi = map(lon, lat)
	# s = map.pcolor(xi, yi, data)
	
	if tb_lef:
		map.drawparallels(np.arange(round(lat_b,0)-lat_bin, round(lat_e,0)+lat_bin, lat_bin), labels=[1,0,0,0],linewidth=0.0,fontsize=8)
	if tb_bot:
		map.drawmeridians(np.arange(round(lon_b,0), round(lon_e,0)+lon_bin, lon_bin), labels=[0,0,0,1],linewidth=0.0,fontsize=8)
	# Add Coastlines, States, and Country Boundaries
	map.drawcoastlines(); #map.drawcountries() #map.drawstates(); #
	masked_obj = np.ma.masked_where(np.isnan(data), data)
	# masked_obj = maskoceans(lon,lat,masked_obj)
	cmap = discrete_cmap(10,colormap)
	cmap.set_bad([1,1,1],alpha = 1.0); cmap.set_over('k'); #cmap.set_under('darkmagenta');
	colormesh = map.pcolormesh(xi, yi, masked_obj,cmap=cmap,vmin=colorbar_min, vmax=colorbar_max,latlon=True)
	pm = np.ma.masked_not_equal(p_value, 1)
	map.pcolor(xi, yi, np.multiply(pm,masked_obj), hatch='+', alpha=0.,lw=0.9,latlon=True)
	plot_rectangle(map, 65,145,5,45); x,y = map(65,43);plt.text(x,y,'',color='k')
	plot_rectangle(map, 235,290,25,50); x,y = map(235,48);plt.text(x,y,'',color='k')
	plot_rectangle(map, -10,40,30,70); x,y = map(30,71);plt.text(x,y,'',color='k')
	return colormesh

def box_clip(lon_s,lon_e,lat_s,lat_e,lon,lat,mask):
	"""
	fill the range outside the box with 0
	"""
	lon = np.array(lon)
	lat = np.array(lat)
	colum_s = [index for index in range(len(lon)) if np.abs(lon-lon_s)[index] == np.min(np.abs(lon-lon_s))][0]
	colum_e = [index for index in range(len(lon)) if np.abs(lon-lon_e)[index] == np.min(np.abs(lon-lon_e))][0]
	row_s = [index for index in range(len(lat)) if np.abs(lat-lat_s)[index] == np.min(np.abs(lat-lat_s))][0]
	row_e = [index for index in range(len(lat)) if np.abs(lat-lat_e)[index] == np.min(np.abs(lat-lat_e))][0]
	if (colum_s> colum_e):
		cache = colum_e; colum_e = colum_s; colum_s = cache;
	if (row_s> row_e):
		cache = row_e; row_e = row_s; row_s = cache;
	mask[:,0:colum_s] =0; mask[:,colum_e:-1] =0
	# plt.imshow(mask,origin='lower');plt.show()
	mask[0:row_s,:] =0; mask[row_e:-1,:] =0
	# plt.imshow(mask,origin='lower');plt.show()
	return mask
	
	
def getArea(lon1,lon2,lat1,lat2):
	'''
	calculate the earth radius in m2
	'''
	radius = 6371000;
	area = (math.pi/180)*np.power(radius,2)*np.abs(lon1-lon2)*\
	(np.abs(np.sin(np.radians(lat1))-np.sin(np.radians(lat2))))
	# print np.nansum(np.nansum(area,axis=1),axis=0)
	return area
	
def mask_weight(region_key,lon,lat,reverse=False):
	"""
	Read in the country mask
	interpolate it to the required resolution grids with lon_interp,lat_interp 
	
	"""
	lon_res = lon[1] - lon[0];lat_res = lat[1] - lat[0];
	lons,lats = np.meshgrid(lon,lat)
	area = getArea(lons,lons+lon_res,lats,lats+lat_res)

	##OCEAN_MASKS FOR COUNTRIES
	ocean_mask = sio.loadmat('/home/s1667168/coding/python/external_data/Euro_USA_AUS_BRICS_STA_720_360.mat')
	lon_mask = ocean_mask['lon'][0,:];
	lat_mask = ocean_mask['lat'][0,:];
	box_region_dic={'All':[0,360,-90,90],'ASIA':[65,145,5,45],'US':[235,290,25,50],'ARCTIC':[0,360,60,90],'TROPICS':[0,360,-28,28],'EUROPE':[0,40,30,70],}
	if (region_key == 'USA' or region_key == 'Europe' or region_key == 'India' or region_key == 'China' or region_key == 'GloLand'):
		mask= ocean_mask[region_key][:]
	elif  region_key in box_region_dic:
		mask= ocean_mask['GloLand'][:]
		box = box_region_dic[region_key]
		mask = box_clip(box[0],box[1],box[2],box[3],lon_mask,lat_mask,mask)
	else:
		print "error region name"
	
	# interpolate from 360*720 to 192*288
	mask[np.isnan(mask)]=0;	mask[mask>0]=1;
	f = interp2d(lon_mask, lat_mask, mask,kind='linear'); mask = f(lon, lat);
	# plt.imshow(mask,origin='lower');plt.show()
	mask[mask >= 1] = 1;mask[mask < 1] = 0;
	# weight each grid cell by its area weight against the total area
	if reverse:
		mask=1-mask
	mask[mask==0] = np.nan
	mask=np.multiply(mask,area); 
	mask_weighted = np.divide(mask,np.nansum(np.nansum(mask,axis=1),axis=0))

	return mask_weighted
	
def data_readin(variable,FREQ):	
	def day2datetime(scenario,days):
		"""
		# convert days from a reference into int datetime 
		# do not take leap years into account
		"""
		date_int = np.empty((len(days)));date_int[:]=np.nan
		if scenario.startswith('F_'):
			start_year =2000
		elif scenario =='EdgRef70AP': start_year =1990
		elif scenario =='EdgTechP': start_year =2180
		elif scenario =='EdgRefP' or scenario =='EdgEneP'  or scenario =='Edg1970': start_year =2000
		elif scenario =='T1970C': 
			start_year =1970
		else: 
			start_year =2010
		start =(start_year*365)+1
		ith=0	
		for iday in days:
			month_days =np.array([31,28,31,30,31,30,31,31,30,31,30,31])
			calendar_days = np.array([0,31,59,90,120,151,181,212,243,273,304,334,365])
			total_days = int(iday) + start; 
			year = total_days//365; 
			remainder =  total_days%365
			if remainder ==0: year=year-1;month=12;day=31
			else: 
				month = 1+[layer for layer in range(len(calendar_days)) if calendar_days[layer]< remainder and calendar_days[layer+1]>=remainder][0]
				day = int(remainder - calendar_days[month-1])
				if day == 0: day = month_days[month-1]
			date_int[ith] = year*10000+month*100+day
			ith=ith+1
		return date_int.astype(int)

	def mon_mean2annual_mean(scenario,time,data):
		annual_mean=np.empty((40,192,288));annual_mean[:]=np.nan
		calendar_day = np.array([31,28,31,30,31,30,31,31,30,31,30,31])
		if scenario=='T1970RCP':
			year_series = range(2020,2050)
		elif scenario=='EdgEne':
			year_series = range(2200,2230)
		elif scenario=='Edg70GO':
			year_series = range(2070,2100)
		else:
			year_series = range(2130,2160)
		for iyear in year_series:
			
			if (iyear == year_series[0] and time[0]//100 >= year_series[0] *100+1):
				layer_b=0
			else:
				layer_b = [layer for layer in range(len(time)) if time[layer]//100 == iyear*100+1][0]  #June01
			if (iyear == year_series[-1] and time[-1]//100 <= year_series[-1] *100+12):
				layer_e=-2
			else:
				layer_e = [layer for layer in range(len(time)) if time[layer]//100  == iyear*100+12][0]  #August 31
			data_cache = data[layer_b:layer_e+1,:,:]
			annual_mean[iyear-year_series[0],:,:] = stats.nanmean(data_cache,axis=0)
		return annual_mean

	def data_netcdf(scenario,FREQ,variable):
		input_path ='/exports/csce/datastore/geos/users/s1667168/CESM_EDGAR/ModelOutput/FullCp/'
		var_path = input_path+scenario+'/'+FREQ+'/atm/'+scenario+'.atm.'+FREQ+'.'+variable+'.nc'
		# print var_path
		nc_fid = nc4.Dataset(var_path,mode='r')
		lat = nc_fid.variables['lat'][:]
		lon = nc_fid.variables['lon'][:]
		days = nc_fid.variables['time'][:]; time = day2datetime(scenario,days);#print time
		data = nc_fid.variables[variable][:]#-273.15
		# if variable=='AODVIS':
			# data[data>1] =np.nan;data[data<0] =np.nan;
		missing_value = nc_fid.variables[variable].missing_value; #print missing_value
		fill_value = nc_fid.variables[variable]._FillValue; #print fill_value
		data[data==missing_value] = np.nan;data[data==fill_value] = np.nan;
		data[data>1] =np.nan;data[data<0] =np.nan;
		nc_fid.close()
		if variable.startswith('BURDEN'):
			data =  10**(6)*data
		var40map = mon_mean2annual_mean(scenario,time,data)
		return lon,lat,var40map
	
	lon,lat,T1970 = data_netcdf('T1970RCP',FREQ,variable)
	_,_,Edg70GO = data_netcdf('Edg70GO',FREQ,variable)
	_,_,EdgRef = data_netcdf('EdgRef',FREQ,variable)
	_,_,EdgEne = data_netcdf('EdgEne',FREQ,variable)
	_,_,EdgTech = data_netcdf('EdgTech',FREQ,variable)
	return lon,lat,T1970,Edg70GO,EdgRef,EdgEne,EdgTech

	
def print_domain_mean(variable,FREQ):
	"""
	This function block is to produce a weighted_mask for specific regions (either administrative or box)
	and then produce the spatial mean (weighted)
	"""

	def dif_std_for_region(var1,var2,mask):
		"""
		for a regional dif and std. the first step is to evaluate the area-weighted mean, and then the differences and average of difference
		"""
		var1_domain_mean = np.nansum(np.nansum(np.multiply(mask,var1),axis=2),axis=1)
		var2_domain_mean =np.nansum(np.nansum(np.multiply(mask,var2),axis=2),axis=1)
		dif =  np.nanmean(var1_domain_mean - var2_domain_mean,axis=0)
		# _,p_value = student_test(var1_domain_mean , var2_domain_mean)
		# p_value = round(p_value,4)
		return dif
	
	lon,lat,T1970,Edg70GO,EdgRef,EdgEne,EdgTech = data_readin(variable,FREQ);
	
	region_dics ={'All':np.empty((3)),'ASIA':np.empty((3)),'EUROPE':np.empty((3)),'US':np.empty((3))}  #,'USA','SESA','EA','India'
	for region_key in region_dics:
		mask = mask_weight(region_key,lon,lat); #print mask
		if variable.startswith( 'AOD' ):
			region_dics[region_key][0] = dif_std_for_region(Edg70GO,T1970,mask)  #total
			region_dics[region_key][1] = dif_std_for_region(EdgRef,EdgEne,mask)  #ene
			region_dics[region_key][2] = dif_std_for_region(EdgRef,EdgTech,mask) ##tech
		else:
			region_dics[region_key][0] = dif_std_for_region(Edg70GO,T1970,mask)  #total
			region_dics[region_key][1] = dif_std_for_region(EdgRef,EdgEne,mask)  #ene
			region_dics[region_key][2] = dif_std_for_region(EdgRef,EdgTech,mask) ##tech		
	return region_dics

def get_AOD(variable,FREQ):
	"""
	Input all the data from the six experiments
	derive the mean dif and sig
	"""
	def mannwhitneyu_test(vairable1,variable2):
		p_threshold=0.05
		size = np.array([np.shape(variable2)[1],np.shape(variable2)[2]]); 
		p_value = np.empty((size[0],size[1]));p_value[:]=np.nan
		# from scipy.stats import ttest_ind as test
		for x in range(size[0]):
			for y in range(size[1]):
				cache1 = vairable1[:,x,y]
				cache2 = variable2[:,x,y]
				if (cache2==cache1).all(): p_value[x,y] = np.nan
				else: _,p_value[x,y] = man_test(cache1,cache2);
		p_value[p_value>p_threshold]=np.nan;p_value[p_value<=p_threshold]=1
		return p_value
	####calculate the difference and their significance
	def diff_sig(vairable1,variable2):
		dif = np.nanmean(vairable1[0:30,:,:],axis=0)-np.nanmean(variable2[0:30,:,:],axis=0)
		sig = mannwhitneyu_test(vairable1[0:30,:,:], variable2[0:30,:,:])
		# sig_dif = np.multiply(dif,sig)
		return dif,sig
	
	if variable == "BURDENOC":
		index ='BURDENPOM'; lon,lat,T1970_P,Edg70GO_P,EdgRef_P,EdgEne_P,EdgTech_P = data_readin(index,FREQ);
		index ='BURDENSOA'; lon,lat,T1970_S,Edg70GO_S,EdgRef_S,EdgEne_S,EdgTech_S = data_readin(index,FREQ);
		T1970 = T1970_P+T1970_S;Edg70GO = Edg70GO_P+Edg70GO_S;EdgRef = EdgRef_P+EdgRef_S;
		EdgEne = EdgEne_P+EdgEne_S; EdgTech = EdgTech_P+EdgTech_S;
	else:
		lon,lat,T1970,Edg70GO,EdgRef,EdgEne,EdgTech = data_readin(variable,FREQ);
	Total2010,Total2010_s = diff_sig(Edg70GO,T1970)
	ENE,ENE_s= diff_sig(EdgRef,EdgEne)
	TECH,TECH_s= diff_sig(EdgRef,EdgTech)
	return lon,lat,Total2010,ENE,TECH,Total2010_s,ENE_s,TECH_s	

def get_emissions():
	def read_emissions(file):
		nc_fid = nc4.Dataset(file,mode='r')
		lat = nc_fid.variables['lat'][:]
		lon = nc_fid.variables['lon'][:]
		BC =np.nanmean(nc_fid.variables['BC'][:],axis=0)*1000*365*24*60*60
		OC =np.nanmean(nc_fid.variables['OC'][:],axis=0)*1000*365*24*60*60
		NMVOC =np.nanmean(nc_fid.variables['NMVOC'][:],axis=0)*1000*365*24*60*60
		SO2 =np.nanmean(nc_fid.variables['SO2'][:],axis=0)*1000*365*24*60*60
		return lon,lat,BC,OC,NMVOC,SO2	
	
	def region_mean(var,mask):
		region_mean = np.nansum(np.nansum(np.multiply(mask,var),axis=1),axis=0)
		return region_mean
	
	emission_path = '/exports/csce/datastore/geos/users/s1667168/CESM_EDGAR/emissions_PP/'
	ref_1970 = emission_path+'EDGAR4.3.1_Sector_merged.1970.nc'
	lon,lat,BC_1970,OC_1970,NMVOC_1970,SO2_1970 = read_emissions(ref_1970)
	ref_2010 = emission_path+'EDGAR4.3.1_Sector_merged.2010.nc'
	lon,lat,BC_2010,OC_2010,NMVOC_2010,SO2_2010 = read_emissions(ref_2010)
	BC =BC_2010-BC_1970;OC =OC_2010-OC_1970;NMVOC =NMVOC_2010-NMVOC_1970;SO2 =SO2_2010-SO2_1970;
	
	region_dics ={'All':np.empty((4)),'ASIA':np.empty((4)),'EUROPE':np.empty((4)),'US':np.empty((4))}  #,'USA','SESA','EA','India'
	for region_key in region_dics:
		mask = mask_weight(region_key,lon,lat); #print mask
		region_dics[region_key][0] = region_mean(BC,mask)  #total
		region_dics[region_key][1] = region_mean(OC,mask)  #ene
		region_dics[region_key][2] = region_mean(NMVOC,mask) ##tech
		region_dics[region_key][3] = region_mean(SO2,mask) ##tech
	return region_dics	
fig = plt.figure(facecolor='White',figsize=[7,12]);pad= 5;

ax = plt.subplot(3,1,1);
ax.annotate('(a) Aerosol emissions'+ r'($\mathrm{\/g\/m^{-2}\/year^{-1}}$)',xy=(0.02,1.03), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='left', va='baseline',rotation='horizontal',fontsize=15)	
def plot_emission_bar(region_dics):
	# print "------"+var+"--------"
	def autolabel(X_pos,values,height_lift):
		## Attach a text label above each bar displaying its height
		height= np.round(np.nan_to_num(values),2);y_pos = height_lift*height
		for i in range(len(height)):
			ax.text(X_pos[i],y_pos[i],'%4.2f' % height[i], ha='center', va='bottom',size=6)
	
	ax.tick_params(axis='both', which='major', direction = 'out',left=True,right=True,bottom=False,top=False, pad=5)
	ax.axhline(y=0,color='k',linewidth = 2);
	ax.set_xlim([-0.5,9.5]);ax.set_xticks(np.arange(0.75,10,2.5));ax.set_xticklabels(('BC','OC','NMVOC','SO2'),fontsize = 10);
	ax.set_ylim([-3,3.0]);ax.set_yticks(np.arange(-3,3.01,1.5));ax.set_yticklabels(np.arange(-3,3.01,1.5),fontsize = 10)
	ax.axvspan(2, 4.5, alpha=0.1, color='r',edgecolor='none');ax.axvspan(7, 9.5, alpha=0.1, color='y',edgecolor='none')

	X_pos=np.arange(0,10,2.5);dis=0.5
	
	region_key = 'All'
	y_value = np.array([10*region_dics[region_key][0],region_dics[region_key][1],region_dics[region_key][2],region_dics[region_key][3]]) 
	print y_value
	rects1=ax.bar(X_pos, y_value, yerr=0, align='center',color='r', ecolor='r',capsize=0,alpha=0.7,width=0.5,lw=0)
	autolabel(X_pos,y_value,1.05)

	region_key = 'ASIA'
	y_value =np.array([10*region_dics[region_key][0],region_dics[region_key][1],region_dics[region_key][2],region_dics[region_key][3]])
	rects2=ax.bar(X_pos+dis*1, y_value, yerr=0, align='center',color='orange', ecolor='orange',capsize=0,alpha=0.7,width=0.5,lw=0)
	autolabel(X_pos+dis*1,y_value,1.05)

	region_key = 'EUROPE'
	y_value =np.array([10*region_dics[region_key][0],region_dics[region_key][1],region_dics[region_key][2],region_dics[region_key][3]])
	rects3=ax.bar(X_pos+dis*2, y_value, yerr=0, align='center',color='g', ecolor='y',capsize=0,alpha=0.7,width=0.5,lw=0)
	autolabel(X_pos+dis*2,y_value,1.05)

	region_key = 'US'
	y_value = np.array([10*region_dics[region_key][0],region_dics[region_key][1],region_dics[region_key][2],region_dics[region_key][3]])
	rects4=ax.bar(X_pos+dis*3, y_value, yerr=0, align='center',color='purple', ecolor='g',capsize=0,alpha=0.7,width=0.5,lw=0)
	autolabel(X_pos+dis*3,y_value,1.05)
	
	return rects1,rects2,rects3,rects4

region_dics = get_emissions();
rects1,rects2,rects3,rects4 = plot_emission_bar(region_dics)
legend1=ax.legend((rects1[0], rects2[0],rects3[0], rects4[0]),\
('Globe', 'Asia','Europe', 'USA'), shadow=False,ncol=2,loc='lower left',fontsize=10)
legend1.get_frame().set_facecolor('white');legend1.get_frame().set_edgecolor('None');legend1.get_frame().set_alpha(0.1)



ax = plt.subplot(3,1,2);FREQ='mon' ; ## burdens
ax.annotate('(b) Aerosol burdens'r'($\mathrm{\/mg\/m^{-2}}$)',xy=(.02,1.03), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='left', va='baseline',rotation='horizontal',fontsize=15)	
index ='BURDENBC'	  
BC_burden_dics = print_domain_mean(index,FREQ);
index ='BURDENPOM'	  
POM_burden_dics = print_domain_mean(index,FREQ);
index ='BURDENSOA'	
SOA_burden_dics = print_domain_mean(index,FREQ);
index ='BURDENSO4'
SO4_burden_dics = print_domain_mean(index,FREQ);
def plot_burden_bar(no):
	# print "------"+var+"--------"
	def autolabel(X_pos,values,height_lift):
		## Attach a text label above each bar displaying its height
		height= np.round(np.nan_to_num(values),2);y_pos = height_lift*height
		for i in range(len(height)):
			ax.text(X_pos[i],y_pos[i],'%4.2f' % height[i], ha='center', va='bottom',size=6)
	
	ax.tick_params(axis='both', which='major', direction = 'out',left=True,right=True,bottom=False,top=False, pad=5)
	ax.axhline(y=0,color='k',linewidth = 2);
	ax.set_xlim([-0.5,9.5]);ax.set_xticks(np.arange(0.75,10,2.5));ax.set_xticklabels(('BC','POM','SOA','SO4'),fontsize = 10);
	ax.set_ylim([-5,5.0]);ax.set_yticks(np.arange(-5,5.01,2.5));ax.set_yticklabels(np.arange(-5,5.01,2.5),fontsize = 10)
	ax.axvspan(2, 4.5, alpha=0.1, color='r',edgecolor='none');ax.axvspan(7, 9.5, alpha=0.1, color='y',edgecolor='none')

	X_pos=np.arange(0,10,2.5);dis=0.5
	
	region_key = 'All'
	y_value = np.array([10*BC_burden_dics[region_key][no],POM_burden_dics[region_key][no],SOA_burden_dics[region_key][no],SO4_burden_dics[region_key][no]]) 
	rects1=ax.bar(X_pos, y_value, yerr=0, align='center',color='r', ecolor='r',capsize=0,alpha=0.7,width=0.5,lw=0)
	autolabel(X_pos,y_value,1.05)

	region_key = 'ASIA'
	y_value =np.array([10*BC_burden_dics[region_key][no],POM_burden_dics[region_key][no],SOA_burden_dics[region_key][no],SO4_burden_dics[region_key][no]])
	rects2=ax.bar(X_pos+dis*1, y_value, yerr=0, align='center',color='orange', ecolor='orange',capsize=0,alpha=0.7,width=0.5,lw=0)
	autolabel(X_pos+dis*1,y_value,1.05)

	region_key = 'EUROPE'
	y_value =np.array([10*BC_burden_dics[region_key][no],POM_burden_dics[region_key][no],SOA_burden_dics[region_key][no],SO4_burden_dics[region_key][no]])
	rects3=ax.bar(X_pos+dis*2, y_value, yerr=0, align='center',color='g', ecolor='y',capsize=0,alpha=0.7,width=0.5,lw=0)
	autolabel(X_pos+dis*2,y_value,1.05)

	region_key = 'US'
	y_value = np.array([10*BC_burden_dics[region_key][no],POM_burden_dics[region_key][no],SOA_burden_dics[region_key][no],SO4_burden_dics[region_key][no]])
	rects4=ax.bar(X_pos+dis*3, y_value, yerr=0, align='center',color='purple', ecolor='g',capsize=0,alpha=0.7,width=0.5,lw=0)
	autolabel(X_pos+dis*3,y_value,1.2)
	
	return rects1,rects2,rects3,rects4
rects1,rects2,rects3,rects4 = plot_burden_bar(no=0)

	
ax = plt.subplot(3,1,3);
index ='AODVIS'	;FREQ='mon';lon,lat,Total2010_AOD,_,_,Total2010_s_AOD,_,_ = get_AOD(index,FREQ);

colorbar_min=-0.10;colorbar_max=0.10;colormap='RdYlBu_r';

ax.annotate('(c) AOD (#)',xy=(.02,1.03), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='left', va='baseline',rotation='horizontal',fontsize=15)	
colormesh0 = spatial_figure(ax,Total2010_AOD,Total2010_s_AOD,lon,lat,colormap,colorbar_min,colorbar_max,tb_lef=False,tb_bot=False)
cbar_ax = fig.add_axes([.09, 0.04, .84, .015])
char = fig.colorbar(colormesh0,orientation='horizontal',extend='both',cax=cbar_ax,ticks=np.round(np.arange(0,1.01,0.20)*(colorbar_max-colorbar_min)+colorbar_min,3))

plt.subplots_adjust(left=0.10, bottom=0.07, right=0.96, top=0.95, wspace=0.04, hspace=0.20); 
plt.savefig('Aerosol_burden_AOD.png', format='png', dpi=1000)
