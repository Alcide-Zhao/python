"""
This is to plot the radiation at TOS (L+S) from the EDGAR six experiments
data inputs are forty years of monthly PRECT+l
	first step is to process the monthly PRECT+l into monthly mean
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
from scipy.stats import mannwhitneyu as man_test
from scipy.stats import ttest_ind as student_test
from scipy.interpolate import interp2d  as interp2d

lib_path = os.path.join(
    os.path.realpath(
        os.path.dirname(__file__)
    ), 
    os.path.pardir,os.path.pardir,os.path.pardir,
)
site.addsitedir(lib_path)
from lib import *



		
def data_readin(variable,FREQ):	
	def day2datetime(scenario,days):
		"""
		# convert days from a reference into int datetime 
		# do not take leap years into account
		"""
		date_int = np.empty((len(days)));date_int[:]=np.nan
		if scenario =='T1970C': start_year =1970
		else: start_year =2010
		start =(start_year*365)
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
			annual = np.empty((192,288));annual[:] = 0.0			
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
			# ### if ther is pnly 11 months, just average over the 11 months
			# if (iyear == year_series[0] and np.shape(data_cache)[0] <=11):
				# for i in range(12-np.shape(data_cache)[0],12):
					# annual = annual+data_cache[i-(12-np.shape(data_cache)[0]),:,:]*calendar_day[i]
				# annual_mean[iyear-year_series[0],:,:] = annual/np.sum(calendar_day[12-np.shape(data_cache)[0]:12])
			# elif (iyear == year_series[-1] and np.shape(data_cache)[0] <=11):
				# for i in range(0,np.shape(data_cache)[0]):
					# annual = annual+data_cache[i,:,:]*calendar_day[i]
				# annual_mean[iyear-year_series[0],:,:] = annual/np.sum(calendar_day[0:np.shape(data_cache)[0]])
			# else:
				# for i in range(0,12):
					# annual = annual+data_cache[i,:,:]*calendar_day[i]
				# annual_mean[iyear-year_series[0],:,:] = annual/365
		# mean_map = stats.nanmean(annual_mean,axis=0)
		return annual_mean

	def data_netcdf(scenario,FREQ,variable):
		input_path ='/exports/csce/datastore/geos/users/s1667168/CESM_EDGAR/ModelOutput/'
		var_path = input_path+scenario+'/'+FREQ+'/atm/'+scenario+'.atm.'+FREQ+'.'+variable+'.nc'
		# print var_path
		nc_fid = nc4.Dataset(var_path,mode='r')
		lat = nc_fid.variables['lat'][:]
		lon = nc_fid.variables['lon'][:]
		days = nc_fid.variables['time'][:]; time = day2datetime(scenario,days);#print time
		data = nc_fid.variables[variable][:]
		nc_fid.close()
		var40map = mon_mean2annual_mean(scenario,time,data)
		return lon,lat,var40map
	
	lon,lat,Edg70GO = data_netcdf('Edg70GO',FREQ,variable)
	_,_,T1970 = data_netcdf('T1970C',FREQ,variable)
	_,_,EdgRef = data_netcdf('EdgRef',FREQ,variable)
	_,_,Edg70Oz = data_netcdf('Edg70Oz',FREQ,variable)
	_,_,EdgEne = data_netcdf('EdgEne',FREQ,variable)
	_,_,EdgTech = data_netcdf('EdgTech',FREQ,variable)
	return lon,lat,T1970,Edg70GO,Edg70Oz,EdgRef,EdgEne,EdgTech
	
def print_domain_mean(variable,FREQ):
	"""
	This function block is to produce a weighted_mask for specific regions (either administrative or box)
	and then produce the spatial mean (weighted)
	"""
	def AreaWeight(lon1,lon2,lat1,lat2):
		'''
		calculate the earth radius in m2
		'''
		radius = 6371000;
		area = (math.pi/180)*np.power(radius,2)*np.abs(lon1-lon2)*\
		(np.abs(np.sin(np.radians(lat1))-np.sin(np.radians(lat2))))
		# print np.nansum(np.nansum(area,axis=1),axis=0)
		return area
		
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

	def mask_weight(region_key,lon,lat):
		"""
		Read in the country mask
		interpolate it to the required resolution grids with lon_interp,lat_interp 
		
		"""
		lon_res = lon[1] - lon[0];lat_res = lat[1] - lat[0];
		lons,lats = np.meshgrid (lon,lat)
		area = AreaWeight(lons,lons+lon_res,lats,lats+lat_res)
		if region_key == 'All':
			mask=area
			mask_weighted = np.divide(mask,np.nansum(np.nansum(mask,axis=1),axis=0))
		else:
			##OCEAN_MASKS FOR COUNTRIES
			ocean_mask = sio.loadmat('/home/s1667168/coding/python/external_data/Euro_StAf_USA_AUS_BRICS_720_360.mat')
			lon_mask = ocean_mask['lon'][0,:];
			lat_mask = ocean_mask['lat'][0,:];
			box_region_dic={'Land':[0,360,-90,90],'ASIA':[65,145,5,45],'EUS':[265,280,30,50],'EA':[100,145,20,50],'SA':[65,100,5,30],'SESA':[295,315,-40,-25]}
			if (region_key == 'USA' or region_key == 'Europe' or region_key == 'India' or region_key == 'China' or region_key == 'Globe'):
				mask= ocean_mask[region_key][:]
			elif (region_key == 'Land' or region_key == 'ASIA' or region_key == 'EA' or region_key == 'SA' or region_key == 'SESA' or region_key == 'EUS'):
				mask= ocean_mask['Globe'][:]
				box = box_region_dic[region_key]
				mask = box_clip(box[0],box[1],box[2],box[3],lon_mask,lat_mask,mask)
			else:
				print "error region name"
			# interpolate from 360*720 to 192*288
			mask[np.isnan(mask)]=0;	mask[mask>0]=1;
			f = interp2d(lon_mask, lat_mask, mask,kind='linear'); 
			mask = f(lon, lat);
			mask[mask >= 1] = 1;mask[mask < 1] = np.nan;mask[0:27,:]=np.nan
			# weight each grid cell by its area weight against the total area
			mask=np.multiply(mask,area);  
			mask_weighted = np.divide(mask,np.nansum(np.nansum(mask,axis=1),axis=0))
			# print np.nansum(np.nansum(mask_weighted,axis=1),axis=0)
		return mask_weighted
		
	def global_mean():
		lon,lat,T1970,Edg70GO,Edg70Oz,EdgRef,EdgEne,EdgTech = data_readin(variable,FREQ);
		mask = mask_weight('All',lon,lat);
		T1970 = np.nansum(np.nansum(np.multiply(mask,T1970),axis=2),axis=1)
		Edg70GO = np.nansum(np.nansum(np.multiply(mask,Edg70GO),axis=2),axis=1)
		Edg70Oz = np.nansum(np.nansum(np.multiply(mask,Edg70Oz),axis=2),axis=1)
		EdgRef = np.nansum(np.nansum(np.multiply(mask,EdgRef),axis=2),axis=1)
		EdgEne = np.nansum(np.nansum(np.multiply(mask,EdgEne),axis=2),axis=1)
		EdgTech = np.nansum(np.nansum(np.multiply(mask,EdgTech),axis=2),axis=1)
		return T1970,Edg70GO,Edg70Oz,EdgRef,EdgEne,EdgTech
	
	T1970,Edg70GO,Edg70Oz,EdgRef,EdgEne,EdgTech = global_mean();
	
	return T1970,Edg70GO,Edg70Oz,EdgRef,EdgEne,EdgTech
	
T1970_LN,_,_,EdgRef_LN,_,_ = print_domain_mean(variable='FLNT',FREQ='mon');
T1970_LU,_,_,EdgRef_LU,_,_ = print_domain_mean(variable='FLUT',FREQ='mon');
T1970_SU,_,_,EdgRef_SU,_,_ = print_domain_mean(variable='FSNTOA',FREQ='mon');
T1970_SN,_,_,EdgRef_SN,_,_ = print_domain_mean(variable='FSNT',FREQ='mon');


print np.nanmean(T1970_SN-T1970_LN)
print np.nanmean(EdgRef_SN-EdgRef_LN)
fig = plt.figure(facecolor='White',figsize=[6,3]);plot_setup();pad= 5;

year = range(0,40); 

ax1 = plt.subplot(1,2,1);
ax1.annotate('(a) 1970',xy=(0.02,1.01), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='left', va='baseline',rotation='horizontal',fontsize=10)	
				
ax1.plot(year,T1970_LN,'-',color="g",linewidth=2,label='Net LW')
ax1.plot(year,T1970_LU,'-',color="k",linewidth=2,label='Upwelling LW')
ax1.plot(year,T1970_SN,'-',color="y",linewidth=2,label='Net TOM SW ')
ax1.plot(year,T1970_SU,'-',color="b",linewidth=2,label='Net TOA SW')


legend = ax1.legend(shadow=False,ncol=2,loc ='upper right')	 
legend.get_frame().set_facecolor('white');legend.get_frame().set_edgecolor('None');legend.get_frame().set_alpha(0)

				
ax1 = plt.subplot(1,2,2);
ax1.annotate('(b) 2010',xy=(0.02,1.01), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='left', va='baseline',rotation='horizontal',fontsize=10)	
				
ax1.plot(year,EdgRef_LN,'-',color="g",linewidth=2,label='Net LW')
ax1.plot(year,EdgRef_LU,'-',color="k",linewidth=2,label='Upwelling LW')
ax1.plot(year,EdgRef_SN,'-',color="y",linewidth=2,label='Net TOM SW ')
ax1.plot(year,EdgRef_SU,'-',color="b",linewidth=2,label='Net TOA SW ')


plt.subplots_adjust(left=0.10, bottom=0.10, right=0.98, top=0.90, wspace=0.20, hspace=0.15); 
plt.savefig('TOA_radiation_TS.png', format='png', dpi=1000)